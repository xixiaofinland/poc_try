import json
import os
import logging
from pathlib import Path
from pathlib import PurePosixPath
from typing import AsyncIterator

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app.openai_utils import extract_reasoning_summary_lines, extract_usage_meta
from app.rag.pipeline import RagPipeline, get_pipeline
from app.schemas import InstrumentDescription, ValuationResult
from app.settings import get_settings
from app.vlm.client import (
    build_image_data_url,
    create_vlm_client,
    describe_instrument,
    parse_description,
    request_description_response,
)

_OPENAPI_TAGS = [
    {"name": "Health", "description": "Service health checks."},
    {"name": "Vision", "description": "Image → structured instrument description."},
    {"name": "Valuation", "description": "Description → valuation result."},
]

app = FastAPI(
    title="Used Instrument Valuation API",
    version="0.1.0",
    description=(
        "API for describing a musical instrument from an image and estimating a "
        "used-market price in JPY."
    ),
    openapi_tags=_OPENAPI_TAGS,
)
logger = logging.getLogger(__name__)

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


@app.get("/api/openapi.json", include_in_schema=False)
async def openapi_json() -> JSONResponse:
    return JSONResponse(app.openapi())


@app.get("/api/docs", include_in_schema=False)
async def swagger_ui() -> Response:
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json", title=f"{app.title} - Swagger UI"
    )


@app.get("/api/redoc", include_in_schema=False)
async def redoc_ui() -> Response:
    return get_redoc_html(openapi_url="/api/openapi.json", title=f"{app.title} - ReDoc")


@app.get("/api/health", tags=["Health"], summary="Health check")
async def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/describe",
    response_model=InstrumentDescription,
    tags=["Vision"],
    summary="Describe an instrument (image → JSON)",
    responses={
        400: {"description": "Bad request"},
        500: {"description": "VLM request failed"},
    },
)
async def describe(image: UploadFile = File(...)) -> InstrumentDescription:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    try:
        payload = await image.read()
        return describe_instrument(payload, image.content_type)
    except ValueError as exc:
        logger.warning("VLM request error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("VLM request failed")
        raise HTTPException(status_code=500, detail="VLM request failed") from exc


@app.post(
    "/api/describe/stream",
    tags=["Vision"],
    summary="Stream a description (SSE)",
    description=(
        "Streams progress events and a final instrument description as "
        "Server-Sent Events (SSE)."
    ),
    responses={
        200: {
            "description": "SSE stream of progress and result events",
            "content": {"text/event-stream": {}},
        },
        400: {"description": "Bad request"},
        500: {"description": "VLM request failed"},
    },
)
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
            settings = get_settings()
            yield _sse_event(
                "log",
                {
                    "code": "vision.model",
                    "meta": {"model": settings.openai_vlm_model},
                },
            )

            response = request_description_response(client, image_url)
            output_text = response.output_text
            for line in extract_reasoning_summary_lines(response):
                yield _sse_event(
                    "log",
                    {"code": "vision.reasoning_summary", "meta": {"text": line}},
                )
            usage_meta = extract_usage_meta(response)
            if usage_meta:
                yield _sse_event("log", {"code": "vision.usage", "meta": usage_meta})
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
            logger.warning("VLM request error: %s", exc)
            yield _sse_event("error", {"message": str(exc)})
        except Exception:
            logger.exception("VLM request failed")
            yield _sse_event("error", {"message": "VLM request failed"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post(
    "/api/estimate",
    response_model=ValuationResult,
    tags=["Valuation"],
    summary="Estimate price (JSON)",
    responses={
        400: {"description": "Bad request"},
        500: {"description": "RAG request failed"},
    },
)
async def estimate(
    description: InstrumentDescription,
    pipeline: RagPipeline = Depends(get_pipeline),
) -> ValuationResult:
    try:
        return pipeline.estimate(description)
    except ValueError as exc:
        logger.warning("RAG request error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("RAG request failed")
        raise HTTPException(status_code=500, detail="RAG request failed") from exc


@app.post(
    "/api/estimate/stream",
    tags=["Valuation"],
    summary="Stream a price estimate (SSE)",
    description=(
        "Streams retrieval / inference progress and a final valuation result as "
        "Server-Sent Events (SSE)."
    ),
    responses={
        200: {
            "description": "SSE stream of progress and result events",
            "content": {"text/event-stream": {}},
        },
        400: {"description": "Bad request"},
        500: {"description": "RAG request failed"},
    },
)
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
            yield _sse_event(
                "log",
                {"code": "rag.model", "meta": {"model": settings.openai_rag_model}},
            )

            response = pipeline.request_estimate_response(query_text, context)
            output_text = response.output_text
            for line in extract_reasoning_summary_lines(response):
                yield _sse_event(
                    "log",
                    {"code": "rag.reasoning_summary", "meta": {"text": line}},
                )
            usage_meta = extract_usage_meta(response)
            if usage_meta:
                yield _sse_event("log", {"code": "rag.usage", "meta": usage_meta})
            result = pipeline.parse_estimate(output_text)
            yield _sse_event("step", {"phase": "rag", "index": 3, "status": "done"})
            yield _sse_event(
                "result", {"phase": "rag", "payload": result.model_dump()}
            )
        except ValueError as exc:
            logger.warning("RAG request error: %s", exc)
            yield _sse_event("error", {"message": str(exc)})
        except Exception:
            logger.exception("RAG request failed")
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
