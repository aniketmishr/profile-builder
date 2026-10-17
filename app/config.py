from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    session_token_secret: str = "dev-only-secret-change-me"
    public_base_url: str = "http://localhost:8000"
    enable_debug_endpoints: bool = False
    log_level: str = "INFO"
    session_token_ttl_seconds: int = 60 * 60 * 24

    # LLM. "none" means no provider: the planner serves its built-in fallback questions.
    llm_provider: str = "none"  # none | gemini
    llm_model: str = ""  # required when llm_provider != none (copy the current model id from the provider)
    gemini_api_key: str = ""
    llm_timeout_seconds: float = 8.0  # planning
    llm_turn_timeout_seconds: float = 4.0  # per-answer interpretation (keeps turns snappy)
    extraction_timeout_seconds: float = 20.0
    max_extracted_facts: int = 20
    auto_extract: bool = True  # start extraction in the background as soon as a debrief completes
    extraction_stale_seconds: int = 120  # a 'running' extraction older than this may be re-run
    precompute_plans: bool = True  # generate the question plan in the background at session intake
    max_questions: int = 7

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Neon/Render hand out postgres:// or postgresql://; we use psycopg 3.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
