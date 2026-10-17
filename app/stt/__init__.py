from functools import lru_cache

from app.config import get_settings
from app.stt.base import Transcriber, TranscriptionError

__all__ = ["Transcriber", "TranscriptionError", "get_transcriber"]


@lru_cache
def get_transcriber() -> Transcriber | None:
    """The one place a speech-to-text provider is chosen. None means voice is disabled."""
    s = get_settings()
    if s.stt_provider == "none":
        return None
    if s.stt_provider == "dev":
        from app.stt.dev import DevTranscriber
        return DevTranscriber()
    if s.stt_provider == "gemini":
        from app.stt.gemini import GeminiTranscriber
        return GeminiTranscriber(s.gemini_api_key, s.stt_model or s.llm_model, s.stt_timeout_seconds)
    raise ValueError(f"unknown STT_PROVIDER: {s.stt_provider!r}")
