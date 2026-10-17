from app.stt.base import TranscriptionError


class DevTranscriber:
    """STT_PROVIDER=dev: returns a fixed transcript so the voice flow can be tried without a provider key.
    Never use it for real answers: it does not listen to the audio."""
    name = "dev"
    model = "stub"

    def transcribe(self, audio: bytes, mime_type: str, language: str | None = None,
                   timeout: float | None = None) -> str:
        if not audio:
            raise TranscriptionError("empty audio")
        return "This is a stub transcript (STT_PROVIDER=dev): the customer prefers WhatsApp and not after 9pm."
