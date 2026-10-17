"""Debrief -> proposed facts -> agent confirmation -> saved profile facts.

Pipeline: request() claims a persisted run, run_extraction() does the LLM work (in the background),
the agent reviews the proposals, and confirm() saves them through services.apply_facts in one transaction.

Trust rules enforced in code, not only in the prompt:
- every proposed fact needs an evidence quote that really appears in one of the agent's answers,
- low confidence, malformed keys, empty values and duplicate keys are dropped (and recorded in `dropped`),
- if the LLM is unavailable or everything it proposed fails validation, the agent's own words are offered as notes,
- nothing reaches the profile until the agent confirms.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app import services
from app.config import get_settings
from app.db import open_session
from app.lookup import require_session as _require_session
from app.llm import LLMError, LLMProvider, generate_structured
from app.logging import log, session_ctx
from app.models import Extraction
from app.prompts import clean, load_prompt
from app.repo import ScopedRepo
from app.schemas import (
    Category, ConfirmIn, ConfirmOut, ExtractedFactOut, ExtractionOut, FactIn, FactOut,
)

PROMPT_NAME = "extractor_v1"
MIN_CONFIDENCE = 0.5
MAX_VALUE_CHARS = 500
MAX_LIST_ITEMS = 10
MIN_EVIDENCE_CHARS = 3
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,59}$")


# ---- what the LLM must produce -------------------------------------------------
class LLMFact(BaseModel):
    category: Category
    key: str = Field(min_length=2, max_length=80)
    value: str | list[str]
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=3, max_length=400)


class LLMExtraction(BaseModel):
    facts: list[LLMFact] = Field(default_factory=list)


# ---- validation helpers (pure functions, unit-tested) ------------------------------
def normalize_text(s: str) -> str:
    """Case, punctuation and whitespace insensitive form used to check quotes."""
    s = unicodedata.normalize("NFKC", s).casefold()
    return " ".join("".join(ch if unicodedata.category(ch)[0] in "LMN" else " " for ch in s).split())


def evidence_supported(evidence: str, answers: list[str]) -> bool:
    """The quote must appear inside a single agent answer (not span two, not come from a question)."""
    needle = normalize_text(evidence)
    if len(needle) < MIN_EVIDENCE_CHARS:
        return False
    return any(needle in normalize_text(a) for a in answers)


def normalize_key(key: str) -> str | None:
    k = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return k if _KEY_RE.match(k) else None


def clean_value(value: object) -> str | list[str] | None:
    if isinstance(value, list):
        items = [" ".join(str(v).split()) for v in value]
        items = list(dict.fromkeys(i[:MAX_VALUE_CHARS] for i in items if i))[:MAX_LIST_ITEMS]
        return items or None
    text = " ".join(str(value or "").split())[:MAX_VALUE_CHARS]
    return text or None


def sanitize(facts: list[LLMFact], answers: list[str], cap: int) -> tuple[list[dict], list[dict]]:
    """Returns (accepted proposals, dropped with reasons)."""
    accepted: list[dict] = []
    dropped: list[dict] = []

    def drop(f: LLMFact, reason: str) -> None:
        dropped.append({"category": f.category, "key": f.key, "value": f.value, "reason": reason})

    for f in facts:
        key, value = normalize_key(f.key), clean_value(f.value)
        evidence = " ".join(f.evidence.split())
        if key is None:
            drop(f, "bad_key")
        elif value is None:
            drop(f, "empty_value")
        elif f.confidence < MIN_CONFIDENCE:
            drop(f, "low_confidence")
        elif not evidence_supported(evidence, answers):
            drop(f, "evidence_not_in_agent_answers")
        else:
            accepted.append(dict(category=f.category, key=key, value=value,
                                 confidence=round(f.confidence, 2), evidence=evidence))

    best: dict[tuple[str, str], dict] = {}
    for p in sorted(accepted, key=lambda p: -p["confidence"]):  # stable: ties keep model order
        k = (p["category"], p["key"])
        if k in best:
            dropped.append({"category": p["category"], "key": p["key"], "value": p["value"], "reason": "duplicate_key"})
        else:
            best[k] = p
    final = list(best.values())
    for p in final[cap:]:
        dropped.append({"category": p["category"], "key": p["key"], "value": p["value"], "reason": "over_cap"})
    return final[:cap], dropped


def fallback_proposals(qa: list[tuple[str, str, str]], cap: int) -> list[dict]:
    """No LLM: offer the agent's own words as notes so nothing they said is lost. Literal, so never invented."""
    out: list[dict] = []
    seen: dict[str, int] = {}
    for _, category, answer in qa:
        value = clean_value(answer)
        if value is None:
            continue
        seen[category] = seen.get(category, 0) + 1
        suffix = "" if seen[category] == 1 else f"_{seen[category]}"
        out.append(dict(category="notes", key=f"note_{category}{suffix}", value=value, confidence=0.5, evidence=value))
    return out[:cap]


# ---- prompts ----------------------------------------------------------------------------
def build_system_prompt() -> str:
    schema = json.dumps(LLMExtraction.model_json_schema(), separators=(",", ":"))
    return load_prompt(PROMPT_NAME).replace("{schema}", schema)


def build_user_prompt(task: dict, qa: list[tuple[str, str, str]]) -> str:
    lines = ["<task_context>", f"type: {clean(task.get('type'))}", f"outcome: {clean(task.get('outcome'))}",
             "</task_context>", "<debrief>"]
    for question, category, answer in qa:
        lines += ["<qa>", f'<question category="{clean(category)}">{clean(question)}</question>',
                  f"<agent_answer>{clean(answer)}</agent_answer>", "</qa>"]
    lines.append("</debrief>")
    return "\n".join(lines)


# ---- persisted run state ------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def _is_stale(row: Extraction) -> bool:
    return row.status == "running" and _now() - _aware(row.started_at) > timedelta(seconds=get_settings().extraction_stale_seconds)


def request(repo: ScopedRepo, session_id: str, force: bool) -> tuple[Extraction, bool]:
    """Claim (or re-claim) the extraction run. Returns (row, should_run).

    force=False (auto, at debrief completion): only starts if none exists.
    force=True (explicit retry): re-runs unless one is already running or the result was confirmed.
    """
    _require_session(repo, session_id)
    debrief = repo.get_debrief(session_id)
    if debrief is None or debrief.state != "complete":
        raise HTTPException(409, "the debrief is not complete yet")
    row = repo.get_extraction(session_id, lock=True)
    if row is None:
        try:
            row = repo.create_extraction(session_id)
        except IntegrityError:
            repo.commit()
            return repo.get_extraction(session_id), False  # a concurrent request claimed it
        repo.commit()
        return row, True
    if row.status == "confirmed":
        if force:
            raise HTTPException(409, "already confirmed; facts are saved")
        return row, False
    if (force and row.status in ("ready", "failed")) or _is_stale(row):
        repo.delete_extracted_facts(session_id)
        row.status, row.attempt = "running", row.attempt + 1
        row.started_at, row.finished_at, row.error = _now(), None, None
        repo.commit()
        return row, True
    return row, False


def _answered_qa(repo: ScopedRepo, session_id: str) -> list[tuple[str, str, str]]:
    questions = {q.id: q for q in repo.debrief_questions(session_id)}
    out = []
    for m in repo.debrief_messages(session_id):
        if m.role == "agent" and m.action == "answer" and m.text.strip():
            q = questions.get(m.question_id)
            out.append((q.text if q else "", q.category if q else "notes", m.text.strip()))
    return out


def _extract(repo: ScopedRepo, session_id: str, llm: LLMProvider | None) -> None:
    row = repo.get_extraction(session_id, lock=True)
    if row is None or row.status != "running":
        return
    session = repo.get_session(session_id)
    qa = _answered_qa(repo, session_id)
    answers = [a for _, _, a in qa]
    cap = get_settings().max_extracted_facts
    proposals: list[dict] = []
    source, error, dropped = "llm", None, []
    row.prompt_version, row.model = PROMPT_NAME, getattr(llm, "model", None)

    if not qa:
        source = "none"
    elif llm is None:
        source, error, proposals = "fallback", "no_llm_configured", fallback_proposals(qa, cap)
    else:
        user = build_user_prompt(session.task_context, qa)
        row.llm_input = user
        try:
            out = generate_structured(llm, system=build_system_prompt(), user=user, schema=LLMExtraction,
                                      timeout=get_settings().extraction_timeout_seconds)
            row.llm_output = out.model_dump()
            proposals, dropped = sanitize(out.facts, answers, cap)
            if out.facts and not proposals:
                source, error, proposals = "fallback", "all_facts_failed_validation", fallback_proposals(qa, cap)
        except LLMError as e:
            source, error, proposals = "fallback", str(e), fallback_proposals(qa, cap)

    for p in proposals:
        repo.add_extracted_fact(session_id, **p)
    row.status, row.source, row.error, row.dropped = "ready", source, error, dropped
    row.finished_at = _now()
    log("extraction ready", source=source, proposed=len(proposals), dropped=len(dropped), error=error,
        prompt_version=PROMPT_NAME, model=row.model)
    repo.commit()


def run_extraction(tenant_id: str, session_id: str, llm: LLMProvider | None) -> None:
    """Background entry point. Never raises: an unexpected crash marks the run 'failed' so it can be retried."""
    db = open_session()
    repo = ScopedRepo(db, tenant_id)
    try:
        session_ctx.set(session_id)
        _extract(repo, session_id, llm)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log("extraction crashed", error=f"{type(e).__name__}: {e}")
        try:
            row = repo.get_extraction(session_id, lock=True)
            if row is not None and row.status == "running":
                row.status, row.error, row.finished_at = "failed", f"{type(e).__name__}: {e}"[:500], _now()
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()


# ---- read ------------------------------------------------------------------------------------
def get_out(repo: ScopedRepo, session_id: str) -> ExtractionOut:
    _require_session(repo, session_id)
    row = repo.get_extraction(session_id)
    if row is None:
        raise HTTPException(404, "extraction not started")
    return ExtractionOut(
        session_id=session_id, status=row.status, source=row.source, prompt_version=row.prompt_version,
        model=row.model, error=row.error, attempt=row.attempt, dropped_count=len(row.dropped or []),
        facts=[ExtractedFactOut.model_validate(f) for f in repo.extracted_facts(session_id)],
    )


# ---- confirm ---------------------------------------------------------------------------------
def confirm(repo: ScopedRepo, session_id: str, body: ConfirmIn) -> ConfirmOut:
    """Save the agent's decisions. Unlisted facts are kept (saving is the confirmation); discarding is explicit.
    Facts and the extraction status change in ONE transaction."""
    session = _require_session(repo, session_id)
    row = repo.get_extraction(session_id, lock=True)
    if row is None:
        raise HTTPException(404, "extraction not started")
    if row.status == "confirmed":
        raise HTTPException(409, "already confirmed")
    if row.status != "ready":
        raise HTTPException(409, f"extraction is {row.status}, not ready")

    proposals = {f.id: f for f in repo.extracted_facts(session_id)}
    decisions = {}
    for d in body.decisions:
        if d.fact_id not in proposals:
            raise HTTPException(422, f"unknown fact_id {d.fact_id}")
        if d.fact_id in decisions:
            raise HTTPException(422, f"duplicate decision for {d.fact_id}")
        if d.action == "edit" and clean_value(d.value) is None:
            raise HTTPException(422, "edit needs a non-empty value")
        decisions[d.fact_id] = d

    facts_in: list[FactIn] = []
    per_fact: dict[tuple[str, str], dict] = {}
    discarded = 0
    for xf in proposals.values():
        d = decisions.get(xf.id)
        action = d.action if d else "keep"
        if action == "discard":
            xf.status, discarded = "discarded", discarded + 1
            continue
        value, confidence, extra = xf.value, xf.confidence, {"agent_edited": False}
        if action == "edit":
            new_value = clean_value(d.value)
            if new_value != xf.value:
                xf.original_value, xf.value, xf.edited = xf.value, new_value, True
                value, confidence = new_value, 1.0  # the agent's own correction
                extra = {"agent_edited": True, "original_value": xf.original_value}
        facts_in.append(FactIn(category=xf.category, key=xf.key, value=value, confidence=confidence, evidence=xf.evidence))
        per_fact[(xf.category, xf.key)] = {**extra, "extracted_fact_id": xf.id}

    base = {"origin": "extraction", "session_id": session_id, "prompt_version": row.prompt_version,
            "model": row.model, "source": row.source, "attempt": row.attempt}
    written, unchanged = [], []
    end_user = repo.get_end_user(session.end_user_id)
    version = end_user.profile_version if end_user else 0
    if facts_in:
        written, unchanged, version = services.apply_facts(
            repo, session.end_user_id, session_id, facts_in, base, per_fact, commit=False)
        saved_ids = {(f.category, f.key): f.id for f in [*written, *unchanged]}
        for xf in proposals.values():
            if xf.status != "discarded":
                xf.status, xf.saved_fact_id = "saved", saved_ids.get((xf.category, xf.key))
    row.status, row.confirmed_at = "confirmed", _now()
    session.status = "profile_saved"
    log("extraction confirmed", saved=len(written), unchanged=len(unchanged), discarded=discarded)
    repo.commit()
    return ConfirmOut(
        saved=[FactOut.model_validate(f) for f in written],
        unchanged=[FactOut.model_validate(f) for f in unchanged],
        discarded=discarded, profile_version=version,
    )
