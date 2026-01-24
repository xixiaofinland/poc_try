from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_vlm_model: str = Field(default="gpt-4o-mini", alias="OPENAI_VLM_MODEL")
    openai_embed_model: str = Field(
        default="text-embedding-3-large", alias="OPENAI_EMBED_MODEL"
    )
    openai_rag_model: str = Field(default="gpt-4o-mini", alias="OPENAI_RAG_MODEL")
    openai_reasoning_effort: str | None = Field(
        default=None, alias="OPENAI_REASONING_EFFORT"
    )
    openai_reasoning_summary: str | None = Field(
        default="auto", alias="OPENAI_REASONING_SUMMARY"
    )
    openai_max_output_tokens: int | None = Field(
        default=None, alias="OPENAI_MAX_OUTPUT_TOKENS"
    )
    openai_temperature: float | None = Field(default=None, alias="OPENAI_TEMPERATURE")
    openai_text_verbosity: str | None = Field(
        default=None, alias="OPENAI_TEXT_VERBOSITY"
    )
    openai_json_mode: bool = Field(default=True, alias="OPENAI_JSON_MODE")
    rag_top_k: int = Field(default=4, alias="RAG_TOP_K")
    rag_persist_dir: str = Field(default=".rag_store", alias="RAG_PERSIST_DIR")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
