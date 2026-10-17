"""The debrief conversation: plan, ask, interpret, advance, finish.

Rules enforced here (not just in prompts):
- at most `max_questions` questions are ever asked (follow-ups count),
- at most one follow-up per planned question, and never a follow-up to a follow-up,
- the agent can skip any question or end early,
- a stale or double-submitted answer is rejected (409) instead of recorded twice,
- turns for one session are serialised with a row lock on the debrief.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import interpreter, planner
from app.config import get_settings
from app.db import open_session
from app.llm import LLMProvider
from app.logging import log, session_ctx
from app.models import Debrief, DebriefQuestion, DebriefSession
from app.repo import ScopedRepo
from app.schemas import (
    AnswerIn, DebriefMessageOut, DebriefProgress, DebriefQuestionOut, DebriefStateOut,
)

SKIP_WORDS = {"skip", "pass", "next"}
CLOSING = "That's everything I needed, thank you!"
ASKED_STATUSES = ("asked", "answered", "skipped")


# ---- helpers ----------------------------------------------------------------
def _require_session(repo: ScopedRepo, session_id: str) -> DebriefSession:
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    session_ctx.set(session_id)
    return session


def _asked_count(qs: list[DebriefQuestion]) -> int:
    return sum(1 for q in qs if q.status in ASKED_STATUSES)


def _current(qs: list[DebriefQuestion]) -> DebriefQuestion | None:
    return next((q for q in qs if q.status == "asked"), None)


def _plan_input(repo: ScopedRepo, session: DebriefSession) -> planner.PlanInput:
    end_user = repo.get_end_user(session.end_user_id)
    agent = repo.get_agent(session.agent_id)
    return planner.PlanInput(
        task=session.task_context,
        end_user_name=end_user.display_name if end_user else "",
        agent_name=agent.name if agent else "",
        locale=session.locale,
        known_facts=[(f.category, f.key, f.value) for f in repo.current_facts(session.end_user_id)],
    )


def _state(session_id: str, debrief: Debrief | None, qs, msgs) -> DebriefStateOut:
    started = bool(msgs)
    cur = _current(qs)
    return DebriefStateOut(
        session_id=session_id,
        state=("not_started" if not started else "complete" if debrief and debrief.state == "complete" else "active"),
        end_reason=debrief.end_reason if debrief else None,
        plan_source=debrief.plan_source if debrief else None,
        current_question_id=cur.id if cur else None,
        progress=DebriefProgress(asked=_asked_count(qs), cap=get_settings().max_questions),
        questions=[DebriefQuestionOut.model_validate(q) for q in qs],
        messages=[DebriefMessageOut.model_validate(m) for m in msgs],
    )


# ---- plan -------------------------------------------------------------------
def ensure_plan(repo: ScopedRepo, session: DebriefSession, llm: LLMProvider | None) -> None:
    """Create the debrief (plan + questions) if it doesn't exist. Safe to call concurrently."""
    if repo.get_debrief(session.id) is not None:
        return
    result = planner.plan_questions(llm, _plan_input(repo, session))
    meta = dict(plan_source=result.source, prompt_version=result.prompt_version, model=result.model,
                plan_latency_ms=result.latency_ms, plan_error=result.error)
    questions = [dict(category=q.category, text=q.text, why=q.why) for q in result.questions]
    try:
        repo.create_debrief(session.id, meta, questions)
    except IntegrityError:
        pass  # someone else created it first; theirs wins
    repo.commit()


def precompute_plan(tenant_id: str, session_id: str, llm: LLMProvider | None) -> None:
    """Background task started at intake so the first question is ready when the chat opens.
    Best effort and in-process: if it never runs, `start` creates the plan on demand."""
    db = open_session()
    try:
        repo = ScopedRepo(db, tenant_id)
        session = repo.get_session(session_id)
        if session is not None:
            session_ctx.set(session_id)
            ensure_plan(repo, session, llm)
    except Exception:  # noqa: BLE001 - never let a background failure surface anywhere
        log("plan precompute failed")
        db.rollback()
    finally:
        db.close()


# ---- start / read -----------------------------------------------------------
def start(repo: ScopedRepo, session_id: str, llm: LLMProvider | None) -> DebriefStateOut:
    """Idempotent: creates the plan if needed and posts the intro + first question once."""
    session = _require_session(repo, session_id)
    ensure_plan(repo, session, llm)
    debrief = repo.get_debrief(session_id, lock=True)
    if not repo.debrief_messages(session_id):
        qs = repo.debrief_questions(session_id)
        first = next(q for q in qs if q.status == "pending")
        first.status = "asked"
        n = sum(1 for q in qs if q.kind == "planned")
        repo.add_debrief_message(session_id, seq=1, role="ai", text=planner.intro_text(_plan_input(repo, session), n),
                                 meta={"kind": "intro"})
        repo.add_debrief_message(session_id, seq=2, role="ai", text=first.text, question_id=first.id,
                                 meta={"kind": first.kind, "category": first.category})
        session.status = "in_progress"
        log("debrief started", plan_source=debrief.plan_source, questions=n)
    repo.commit()
    return _state(session_id, debrief, repo.debrief_questions(session_id), repo.debrief_messages(session_id))


def get_state(repo: ScopedRepo, session_id: str) -> DebriefStateOut:
    _require_session(repo, session_id)
    return _state(session_id, repo.get_debrief(session_id), repo.debrief_questions(session_id),
                  repo.debrief_messages(session_id))


# ---- turns ------------------------------------------------------------------
def submit(repo: ScopedRepo, llm: LLMProvider | None, session_id: str, body: AnswerIn) -> DebriefStateOut:
    session = _require_session(repo, session_id)
    debrief = repo.get_debrief(session_id, lock=True)
    if debrief is None:
        raise HTTPException(409, "debrief not started")
    if debrief.state == "complete":
        raise HTTPException(409, "debrief already complete")
    qs = repo.debrief_questions(session_id)
    current = _current(qs)
    if current is None:
        raise HTTPException(409, "debrief not started")
    if body.question_id != current.id:
        raise HTTPException(409, "that question is no longer the current one")

    action, text = body.action, (body.text or "").strip()
    if action == "answer":
        if not text:
            raise HTTPException(422, "text is required when action is 'answer'")
        if text.lower().strip(" .!") in SKIP_WORDS:
            action, text = "skip", ""

    msgs = repo.debrief_messages(session_id)
    counter = {"seq": msgs[-1].seq if msgs else 0}

    def say(role: str, text_: str, **kw):
        counter["seq"] += 1
        return repo.add_debrief_message(session_id, seq=counter["seq"], role=role, text=text_, **kw)

    cap = get_settings().max_questions
    if action == "end":
        say("agent", "", question_id=current.id, action="end")
        current.status = "dropped"
        _finish(session, debrief, qs, "agent_ended", say)
    elif action == "skip":
        say("agent", "", question_id=current.id, action="skip")
        current.status = "skipped"
        _advance(session, debrief, qs, say)
    else:
        follow_up_ok = (
            current.kind == "planned"
            and not any(q.parent_id == current.id for q in qs)
            and _asked_count(qs) < cap
        )
        pending = [(f"q{q.seq}", q.text) for q in qs if q.status == "pending"]
        interp = interpreter.interpret_answer(
            llm, question=current.text, category=current.category, answer=text,
            pending=pending, follow_up_allowed=follow_up_ok,
        )
        say("agent", text, question_id=current.id, action="answer", meta=interp.meta())
        current.status = "answered"
        for q in qs:
            if q.status == "pending" and f"q{q.seq}" in interp.covered:
                q.status = "covered"
        if interp.follow_up and follow_up_ok:
            fu = repo.add_debrief_question(
                session_id, seq=max(q.seq for q in qs) + 1, category=current.category, text=interp.follow_up,
                why="follow-up to an ambiguous answer", kind="follow_up", parent_id=current.id, status="asked",
            )
            qs.append(fu)
            say("ai", fu.text, question_id=fu.id, meta={"kind": "follow_up", "category": fu.category})
        else:
            _advance(session, debrief, qs, say)

    log("debrief turn", action=action, question_id=current.id, state=debrief.state)
    repo.commit()
    return _state(session_id, debrief, qs, repo.debrief_messages(session_id))


def _advance(session, debrief, qs, say) -> None:
    cap = get_settings().max_questions
    nxt = next((q for q in qs if q.status == "pending"), None) if _asked_count(qs) < cap else None
    if nxt is None:
        _finish(session, debrief, qs, "question_cap" if any(q.status == "pending" for q in qs) else "all_answered", say)
        return
    nxt.status = "asked"
    say("ai", nxt.text, question_id=nxt.id, meta={"kind": nxt.kind, "category": nxt.category})


def _finish(session, debrief, qs, reason: str, say) -> None:
    for q in qs:
        if q.status == "pending":
            q.status = "dropped"
    debrief.state = "complete"
    debrief.end_reason = reason
    debrief.completed_at = datetime.now(timezone.utc)
    session.status = "debrief_complete"
    say("ai", CLOSING, meta={"kind": "closing", "end_reason": reason})
