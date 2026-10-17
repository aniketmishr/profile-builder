"""Provider-agnostic LLM layer.

A provider only has to implement `complete_json(system, user) -> str` (raw text that should be
JSON). Parsing, validation against a Pydantic schema and the one-shot repair retry live in
`generate_structured`, so swapping providers never changes extraction/planning behaviour.
"""
import json
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Provider unreachable/failed, or the model never produced valid output."""


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, *, system: str, user: str) -> str: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _strip_fences(raw: str) -> str:
    return _FENCE.sub("", raw.strip())


def _short_errors(err: ValidationError | json.JSONDecodeError) -> str:
    if isinstance(err, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in err.errors()[:4])
    return f"not valid JSON ({err.msg})"


def generate_structured(
    provider: LLMProvider, *, system: str, user: str, schema: type[T], max_repairs: int = 1
) -> T:
    """Ask for JSON, validate it, and on failure ask once more showing the validation errors."""
    prompt = user
    last = "no attempt made"
    for _ in range(max_repairs + 1):
        raw = provider.complete_json(system=system, user=prompt)
        try:
            return schema.model_validate_json(_strip_fences(raw))
        except (ValidationError, json.JSONDecodeError) as e:
            last = _short_errors(e)
            prompt = (
                f"{user}\n\nYour previous reply was rejected: {last}. "
                "Reply again with ONLY valid JSON that matches the schema."
            )
    raise LLMError(f"invalid structured output after {max_repairs + 1} attempts: {last}")
