from functools import lru_cache
from pathlib import Path

from openai import OpenAI
from langchain_openai import OpenAIEmbeddings

from app.openai_utils import build_responses_create_kwargs, extract_json_object
from app.rag.seed import load_seed_documents
from app.rag.store import RagResult, RagStore
from app.schemas import InstrumentDescription, ValuationResult
from app.settings import get_settings

RAG_PROMPT = """
You are a pricing analyst for used musical instruments. Given a target instrument
summary and a set of retrieved reference records, estimate a fair market price
in JPY. Return ONLY valid JSON with this schema:
{
  "price_jpy": integer,
  "range_jpy": [integer, integer],
  "confidence": number,
  "rationale": string,
  "evidence": string[]
}
Rules:
- confidence is between 0 and 1.
- range_jpy must include price_jpy and be ordered low to high.
- rationale and evidence must be in Japanese.
- If references are thin, lower confidence and say so.
"""


class RagPipeline:
    def __init__(self, store: RagStore, client: OpenAI) -> None:
        self.store = store
        self.client = client

    def estimate(self, description: InstrumentDescription) -> ValuationResult:
        settings = get_settings()
        query_text = self.build_query(description)
        entries = self.store.query(query_text, settings.rag_top_k)
        context = self.build_context(entries)
        output_text = self.request_estimate(query_text, context)
        return self.parse_estimate(output_text)

    def build_query(self, description: InstrumentDescription) -> str:
        return self._build_query(description)

    def build_context(self, entries: list[RagResult]) -> str:
        return self._build_context(entries)

    def request_estimate_response(self, query_text: str, context: str):
        settings = get_settings()
        return self.client.responses.create(
            model=settings.openai_rag_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": RAG_PROMPT},
                        {
                            "type": "input_text",
                            "text": f"Target\n{query_text}\n\nReferences\n{context}",
                        },
                    ],
                }
            ],
            **build_responses_create_kwargs(model=settings.openai_rag_model, force_json=True),
        )

    def request_estimate(self, query_text: str, context: str) -> str:
        response = self.request_estimate_response(query_text, context)
        return response.output_text

    @staticmethod
    def parse_estimate(output_text: str) -> ValuationResult:
        data = extract_json_object(output_text)
        return ValuationResult.model_validate(data)

    @staticmethod
    def _build_query(description: InstrumentDescription) -> str:
        parts = [
            f"category: {description.category}",
            f"brand: {description.brand}",
            f"model: {description.model}",
            f"year: {description.year or ''}",
            f"condition: {description.condition}",
            f"materials: {', '.join(description.materials)}",
            f"features: {', '.join(description.features)}",
            f"notes: {description.notes}",
        ]
        return "\n".join(part for part in parts if part.split(": ", 1)[1])

    @staticmethod
    def _build_context(entries: list[RagResult]) -> str:
        if not entries:
            return "(no references found)"

        blocks = []
        for entry in entries:
            metadata = entry.document.metadata
            title = metadata.get("title", "unknown")
            price = metadata.get("price_jpy", "unknown")
            source = metadata.get("source", "unknown")
            content = entry.document.page_content
            blocks.append(
                f"- {title} | price_jpy: {price} | source: {source}\n  {content}"
            )
        return "\n".join(blocks)


@lru_cache
def get_pipeline() -> RagPipeline:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    embeddings = OpenAIEmbeddings(
        api_key=settings.openai_api_key, model=settings.openai_embed_model
    )
    persist_dir = Path(settings.rag_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    store = RagStore(embeddings, persist_dir)
    seed_path = Path(__file__).parent / "data" / "seed.jsonl"
    store.add_documents(load_seed_documents(seed_path))

    client = OpenAI(api_key=settings.openai_api_key)
    return RagPipeline(store=store, client=client)
