import json
import os
from pathlib import Path
from pathlib import PurePosixPath
from typing import AsyncIterator

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.rag.pipeline import RagPipeline, get_pipeline
from app.schemas import InstrumentDescription, ValuationResult
from app.settings import get_settings
from app.vlm.client import (
    build_image_data_url,
    create_vlm_client,
    describe_instrument,
    parse_description,
    request_description,
)

app = FastAPI(title="Used Instrument Valuation API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _frontend_candidates() -> list[Path]:
    candidates: list[Path] = []

    env_path = os.environ.get("FRONTEND_DIST_DIR")
    if env_path:
        candidates.append(Path(env_path))

    candidates.append(Path("/app/frontend_dist"))
    return candidates


def _resolve_frontend_dist_dir() -> Path | None:
    for dist_dir in _frontend_candidates():
        if not dist_dir.is_dir():
            continue
        if not (dist_dir / "index.html").is_file():
            continue
        return dist_dir
    return None


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/describe", response_model=InstrumentDescription)
async def describe(image: UploadFile = File(...)) -> InstrumentDescription:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    try:
        payload = await image.read()
        return describe_instrument(payload, image.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="VLM request failed") from exc


@app.post("/api/describe/stream")
async def describe_stream(image: UploadFile = File(...)) -> StreamingResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    async def event_generator() -> AsyncIterator[str]:
        try:
            yield _sse_event("log", {"code": "vision.upload_received"})
            yield _sse_event(
                "step", {"phase": "vision", "index": 0, "status": "start"}
            )
            payload = await image.read()
            yield _sse_event("step", {"phase": "vision", "index": 0, "status": "done"})
            yield _sse_event(
                "step", {"phase": "vision", "index": 1, "status": "start"}
            )
            client = create_vlm_client()
            image_url = build_image_data_url(payload, image.content_type)
            yield _sse_event("step", {"phase": "vision", "index": 1, "status": "done"})
            yield _sse_event("log", {"code": "vision.image_encoded"})
            yield _sse_event("log", {"code": "vision.request_sent"})
            yield _sse_event(
                "step", {"phase": "vision", "index": 2, "status": "start"}
            )
            output_text = request_description(client, image_url)
            yield _sse_event("step", {"phase": "vision", "index": 2, "status": "done"})
            yield _sse_event(
                "step", {"phase": "vision", "index": 3, "status": "start"}
            )
            description = parse_description(output_text)
            yield _sse_event("step", {"phase": "vision", "index": 3, "status": "done"})
            yield _sse_event("log", {"code": "vision.response_parsed"})
            yield _sse_event(
                "result", {"phase": "vision", "payload": description.model_dump()}
            )
        except ValueError as exc:
            yield _sse_event("error", {"message": str(exc)})
        except Exception:
            yield _sse_event("error", {"message": "VLM request failed"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/estimate", response_model=ValuationResult)
async def estimate(
    description: InstrumentDescription,
    pipeline: RagPipeline = Depends(get_pipeline),
) -> ValuationResult:
    try:
        return pipeline.estimate(description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="RAG request failed") from exc


@app.post("/api/estimate/stream")
async def estimate_stream(
    description: InstrumentDescription,
    pipeline: RagPipeline = Depends(get_pipeline),
) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        try:
            settings = get_settings()
            yield _sse_event("log", {"code": "rag.query_build"})
            yield _sse_event("step", {"phase": "rag", "index": 0, "status": "start"})
            query_text = pipeline.build_query(description)
            yield _sse_event("step", {"phase": "rag", "index": 0, "status": "done"})
            yield _sse_event("log", {"code": "rag.retrieve_start"})
            yield _sse_event("step", {"phase": "rag", "index": 1, "status": "start"})
            entries = pipeline.store.query(query_text, settings.rag_top_k)
            yield _sse_event("step", {"phase": "rag", "index": 1, "status": "done"})
            yield _sse_event(
                "log", {"code": "rag.retrieve_done", "meta": {"count": len(entries)}}
            )
            yield _sse_event("log", {"code": "rag.context_build"})
            yield _sse_event("step", {"phase": "rag", "index": 2, "status": "start"})
            context = pipeline.build_context(entries)
            yield _sse_event("step", {"phase": "rag", "index": 2, "status": "done"})
            yield _sse_event("log", {"code": "rag.request_sent"})
            yield _sse_event("step", {"phase": "rag", "index": 3, "status": "start"})
            output_text = pipeline.request_estimate(query_text, context)
            result = pipeline.parse_estimate(output_text)
            yield _sse_event("step", {"phase": "rag", "index": 3, "status": "done"})
            yield _sse_event(
                "result", {"phase": "rag", "payload": result.model_dump()}
            )
        except ValueError as exc:
            yield _sse_event("error", {"message": str(exc)})
        except Exception:
            yield _sse_event("error", {"message": "RAG request failed"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/api/_debug/frontend", include_in_schema=False)
async def debug_frontend() -> dict:
    dist_dir = _resolve_frontend_dist_dir()
    candidates = []
    for candidate in _frontend_candidates():
        candidates.append(
            {
                "path": str(candidate),
                "is_dir": candidate.is_dir(),
                "has_index": (candidate / "index.html").is_file(),
            }
        )

    payload: dict = {
        "frontend_dist_dir": str(dist_dir) if dist_dir else None,
        "env_FRONTEND_DIST_DIR": os.environ.get("FRONTEND_DIST_DIR"),
        "candidates": candidates,
    }

    if dist_dir:
        entries = []
        for entry in sorted(dist_dir.iterdir(), key=lambda p: p.name):
            if len(entries) >= 50:
                break
            entries.append({"name": entry.name, "is_dir": entry.is_dir()})
        payload["entries"] = entries

    return payload


@app.get("/", include_in_schema=False)
async def frontend_index() -> Response:
    dist_dir = _resolve_frontend_dist_dir()
    if not dist_dir:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(dist_dir / "index.html")


@app.get("/{path:path}", include_in_schema=False)
async def frontend_assets(path: str) -> Response:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    dist_dir = _resolve_frontend_dist_dir()
    if not dist_dir:
        raise HTTPException(status_code=404, detail="Not Found")

    requested = PurePosixPath(path)
    if requested.is_absolute() or ".." in requested.parts:
        raise HTTPException(status_code=400, detail="Bad path")

    file_path = dist_dir / requested.as_posix()
    if file_path.is_file():
        return FileResponse(file_path)

    if requested.suffix:
        raise HTTPException(status_code=404, detail="Not Found")

    return FileResponse(dist_dir / "index.html")
