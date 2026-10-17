from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider, generate_structured

__all__ = ["LLMError", "LLMProvider", "generate_structured", "get_llm"]


@lru_cache
def get_llm() -> LLMProvider | None:
    """The one place a provider is chosen. Returns None when no LLM is configured."""
    s = get_settings()
    if s.llm_provider == "none":
        return None
    if s.llm_provider == "gemini":
        from app.llm.gemini import GeminiProvider
        return GeminiProvider(s.gemini_api_key, s.llm_model, s.llm_timeout_seconds)
    raise ValueError(f"unknown LLM_PROVIDER: {s.llm_provider!r}")
