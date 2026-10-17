"""Per-answer interpretation: is the answer clear, does it already cover later questions?

One small LLM call per answer. If there is no provider or the call fails, the safe default is used
(treat the answer as clear, cover nothing), so the debrief keeps moving.
"""
import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm import LLMError, LLMProvider, generate_structured
from app.logging import log
from app.prompts import clean, load_prompt

PROMPT_NAME = "interpreter_v1"
MAX_ANSWER_CHARS = 2000


class LLMInterpretation(BaseModel):
    clarity: Literal["clear", "ambiguous"]
    follow_up: str | None = Field(default=None, max_length=200)
    covered_question_ids: list[str] = Field(default_factory=list)


@dataclass
class Interpretation:
    clarity: Literal["clear", "ambiguous"] = "clear"
    follow_up: str | None = None
    covered: list[str] = field(default_factory=list)  # labels like "q3"
    source: Literal["llm", "fallback"] = "fallback"
    prompt_version: str = PROMPT_NAME
    model: str | None = None
    error: str | None = None

    def meta(self) -> dict:
        return {"clarity": self.clarity, "follow_up": self.follow_up, "covered": self.covered,
                "source": self.source, "prompt_version": self.prompt_version, "model": self.model,
                "error": self.error}


def build_system_prompt() -> str:
    schema = json.dumps(LLMInterpretation.model_json_schema(), separators=(",", ":"))
    return load_prompt(PROMPT_NAME).replace("{schema}", schema)


def build_user_prompt(question: str, category: str, answer: str, pending: list[tuple[str, str]],
                      follow_up_allowed: bool) -> str:
    lines = [
        f'<current_question category="{clean(category)}">{clean(question)}</current_question>',
        f"<follow_up_allowed>{'true' if follow_up_allowed else 'false'}</follow_up_allowed>",
        "<remaining_questions>",
        *[f"- {label}: {clean(text)}" for label, text in pending],
        "</remaining_questions>",
        "<agent_answer>",
        clean(answer)[:MAX_ANSWER_CHARS],
        "</agent_answer>",
    ]
    return "\n".join(lines)


def interpret_answer(
    llm: LLMProvider | None, *, question: str, category: str, answer: str,
    pending: list[tuple[str, str]], follow_up_allowed: bool,
) -> Interpretation:
    if llm is None:
        return Interpretation(error="no_llm_configured")
    try:
        out = generate_structured(
            llm, system=build_system_prompt(),
            user=build_user_prompt(question, category, answer, pending, follow_up_allowed),
            schema=LLMInterpretation, timeout=get_settings().llm_turn_timeout_seconds,
        )
    except LLMError as e:
        log("interpretation failed, using default", error=str(e))
        return Interpretation(error=str(e), model=getattr(llm, "model", None))

    valid = {label for label, _ in pending}
    covered = [c for c in dict.fromkeys(out.covered_question_ids) if c in valid]  # ignore made-up ids
    follow_up = " ".join((out.follow_up or "").split()) or None
    clarity = out.clarity
    if clarity == "ambiguous" and (not follow_up_allowed or not follow_up):
        clarity, follow_up = "clear", None  # nothing we can or should ask: move on
    if clarity == "clear":
        follow_up = None
    return Interpretation(clarity, follow_up, covered, "llm", PROMPT_NAME, getattr(llm, "model", None))
