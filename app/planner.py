"""Debrief question planning.

plan_questions() asks the LLM for a short, task-aware list of questions. If there is no provider,
or it fails or returns invalid output, a deterministic fallback plan is served instead, so the
debrief can always start. Question count is capped in code, never only in the prompt.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm import LLMError, LLMProvider, generate_structured
from app.logging import log
from app.prompts import load_prompt
from app.schemas import Category

PROMPT_NAME = "planner_v1"
MAX_EXCERPT_CHARS = 2000
MAX_KNOWN_FACTS = 20


# ---- schemas ----------------------------------------------------------------
class LLMQuestion(BaseModel):
    """What the LLM must produce. Ids are assigned by us, never trusted from the model."""
    category: Category
    text: str = Field(min_length=8, max_length=220)
    why: str = Field(default="", max_length=240)  # short rationale, kept for audit/debugging


class LLMPlan(BaseModel):
    questions: list[LLMQuestion] = Field(min_length=2)


class PlannedQuestion(BaseModel):
    id: str
    category: Category
    text: str
    why: str = ""


@dataclass
class PlanInput:
    task: dict
    end_user_name: str = ""
    agent_name: str = ""
    locale: str | None = None
    known_facts: list[tuple[str, str, object]] = field(default_factory=list)  # (category, key, value)


@dataclass
class PlanResult:
    questions: list[PlannedQuestion]
    source: Literal["llm", "fallback"]
    prompt_version: str
    model: str | None
    latency_ms: float
    error: str | None = None


# ---- prompt building --------------------------------------------------------
def build_system_prompt() -> str:
    schema = json.dumps(LLMPlan.model_json_schema(), separators=(",", ":"))
    return load_prompt(PROMPT_NAME).replace("{schema}", schema)


def _clean(text: object) -> str:
    return str(text or "").replace("</", "<\\/").strip()


def build_user_prompt(inp: PlanInput) -> str:
    t = inp.task
    lines = [
        "<task>",
        f"type: {_clean(t.get('type'))}",
        f"title: {_clean(t.get('title'))}",
        f"outcome: {_clean(t.get('outcome'))}",
        f"channel: {_clean(t.get('channel'))}",
        f"duration_sec: {_clean(t.get('duration_sec'))}",
        "</task>",
        f"<customer>{_clean(inp.end_user_name)}</customer>",
        f"<agent>{_clean(inp.agent_name)}</agent>",
        f"<locale>{_clean(inp.locale)}</locale>",
        "<known_profile_facts>",
    ]
    for category, key, value in inp.known_facts[:MAX_KNOWN_FACTS]:
        lines.append(f"- {_clean(category)}.{_clean(key)}: {_clean(value)}")
    lines += [
        "</known_profile_facts>",
        "<transcript_excerpt>",
        _clean(t.get("transcript_excerpt"))[:MAX_EXCERPT_CHARS],
        "</transcript_excerpt>",
    ]
    return "\n".join(lines)


# ---- fallback ---------------------------------------------------------------
_FALLBACKS: dict[str, list[tuple[str, str]]] = {
    "refund": [
        ("contact_preferences", "Did {name} say how or when they'd like to be contacted next time?"),
        ("pain_points", "Was there anything that frustrated {name} that we should avoid next time?"),
        ("constraints", "Did {name} mention any preference for how refunds or credits are handled?"),
        ("personal_context", "Anything about who uses the account or the products worth remembering?"),
    ],
    "onboard": [
        ("products_and_usage", "Which products or features is {name} mainly planning to use?"),
        ("communication_style", "How does {name} prefer to be walked through things: short steps or detail?"),
        ("constraints", "Any budget, timing or accessibility needs {name} mentioned?"),
        ("contact_preferences", "Did {name} say how they'd like to be contacted from here on?"),
    ],
    "troubleshoot": [
        ("products_and_usage", "Which product, plan or device was {name} using when this came up?"),
        ("pain_points", "What part of the problem frustrated {name} the most?"),
        ("communication_style", "Is {name} comfortable with technical detail, or do they prefer plain steps?"),
        ("contact_preferences", "Did {name} say how they'd like follow-ups to reach them?"),
    ],
    "default": [
        ("contact_preferences", "Did {name} say how or when they'd like to be contacted next time?"),
        ("constraints", "Any budget, timing or other constraints {name} mentioned?"),
        ("pain_points", "Was there anything that frustrated {name} that we should avoid next time?"),
        ("personal_context", "Anything else about {name}'s situation worth remembering?"),
    ],
}


def fallback_plan(task_type: str, end_user_name: str) -> list[PlannedQuestion]:
    t = (task_type or "").lower()
    key = next((k for k in ("refund", "onboard", "troubleshoot") if k in t), "default")
    name = end_user_name.split()[0] if end_user_name.strip() else "the customer"
    return [
        PlannedQuestion(id=f"q{i}", category=cat, text=text.format(name=name), why="fallback template")
        for i, (cat, text) in enumerate(_FALLBACKS[key], start=1)
    ]


# ---- main entry -------------------------------------------------------------
def intro_text(inp: PlanInput, n: int) -> str:
    who = inp.end_user_name or "the customer"
    title = inp.task.get("title") or "this task"
    return f"Quick debrief on {who}: {title}. {n} short question{'s' if n != 1 else ''}, skip any you like."


def _finalize(questions: list[LLMQuestion], cap: int) -> list[PlannedQuestion]:
    seen: set[str] = set()
    out: list[PlannedQuestion] = []
    for q in questions:
        text = " ".join(q.text.split())
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(PlannedQuestion(id=f"q{len(out) + 1}", category=q.category, text=text, why=q.why.strip()))
        if len(out) == cap:
            break
    return out


def plan_questions(llm: LLMProvider | None, inp: PlanInput) -> PlanResult:
    start = time.perf_counter()
    cap = get_settings().max_questions

    def done(questions, source, error=None) -> PlanResult:
        ms = round((time.perf_counter() - start) * 1000, 1)
        log("debrief plan ready", source=source, n=len(questions), latency_ms=ms,
            prompt_version=PROMPT_NAME, model=getattr(llm, "model", None), error=error)
        return PlanResult(questions, source, PROMPT_NAME, getattr(llm, "model", None), ms, error)

    fb = lambda: fallback_plan(inp.task.get("type", ""), inp.end_user_name)[:cap]  # noqa: E731
    if llm is None:
        return done(fb(), "fallback", "no_llm_configured")
    try:
        plan = generate_structured(
            llm, system=build_system_prompt(), user=build_user_prompt(inp), schema=LLMPlan
        )
    except LLMError as e:
        return done(fb(), "fallback", str(e))
    questions = _finalize(plan.questions, cap)
    if len(questions) < 2:
        return done(fb(), "fallback", "llm returned too few distinct questions")
    return done(questions, "llm")
