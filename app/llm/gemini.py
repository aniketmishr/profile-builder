import time

import httpx

from app.llm.base import LLMError

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TRANSIENT = {429, 500, 502, 503, 504}


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 8.0, client: httpx.Client | None = None):
        if not api_key or not model:
            raise ValueError("GEMINI_API_KEY and LLM_MODEL are required for the gemini provider")
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._client = client or httpx.Client()

    def complete_json(self, *, system: str, user: str, timeout: float | None = None) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
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
                    try:
                        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError, ValueError):
                        raise LLMError("gemini returned no text (blocked or empty response)")
                last = f"http {r.status_code}"
                if r.status_code not in _TRANSIENT:
                    break
            if attempt == 0:
                time.sleep(0.4)
        raise LLMError(f"gemini request failed: {last}")
