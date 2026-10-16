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
