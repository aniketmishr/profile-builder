"""Provider-agnostic speech-to-text. A provider only implements `transcribe`; the job around it lives in app/voice.py."""
from typing import Protocol


class TranscriptionError(Exception):
    """The provider failed, or the audio contained no intelligible speech."""


class Transcriber(Protocol):
    name: str
    model: str

    def transcribe(self, audio: bytes, mime_type: str, language: str | None = None,
                   timeout: float | None = None) -> str: ...
