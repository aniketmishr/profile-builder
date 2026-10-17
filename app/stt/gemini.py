import base64
import re
import time

import httpx

from app.llm.gemini import BASE_URL
from app.stt.base import TranscriptionError

_TRANSIENT = {429, 500, 502, 503, 504}
_PROMPT = (
    "Transcribe this audio exactly as spoken, in the language(s) spoken. Do not translate, summarise or add "
    "commentary. Output only the transcript text. If there is no intelligible speech, output exactly NO_SPEECH."
)
MAX_TRANSCRIPT_CHARS = 4000


class GeminiTranscriber:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0, client: httpx.Client | None = None):
        if not api_key or not model:
            raise ValueError("GEMINI_API_KEY and STT_MODEL (or LLM_MODEL) are required for the gemini transcriber")
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._client = client or httpx.Client()

    def transcribe(self, audio: bytes, mime_type: str, language: str | None = None,
                   timeout: float | None = None) -> str:
        hint = f" The speaker may use these locales or languages: {language}." if language else ""
        body = {
            "contents": [{"role": "user", "parts": [
                {"text": _PROMPT + hint},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio).decode()}},
            ]}],
            "generationConfig": {"temperature": 0},
        }
        url = f"{BASE_URL}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}  # header, not query string: keeps the key out of URLs/logs
        last = "unknown error"
        for attempt in range(2):  # one retry on transient failures
            try:
                r = self._client.post(url, json=body, headers=headers, timeout=timeout or self._timeout)
            except httpx.TransportError as e:
                last = f"transport error: {type(e).__name__}"
            else:
                if r.status_code == 200:
                    return self._text(r)
                last = f"http {r.status_code}"
                if r.status_code not in _TRANSIENT:
                    break
            if attempt == 0:
                time.sleep(0.4)
        raise TranscriptionError(f"gemini transcription failed: {last}")

    @staticmethod
    def _text(r: httpx.Response) -> str:
        try:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError):
            raise TranscriptionError("gemini returned no text for this audio")
        text = re.sub(r"^```\w*\s*|\s*```$", "", text.strip()).strip()
        if not text or text.upper().strip(" .") == "NO_SPEECH":
            raise TranscriptionError("no speech detected in the recording")
        return text[:MAX_TRANSCRIPT_CHARS]
