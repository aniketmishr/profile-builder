"""Small lookups shared by the debrief, extraction and voice modules (kept here to avoid import cycles)."""
from fastapi import HTTPException

from app.logging import session_ctx
from app.models import DebriefQuestion, DebriefSession
from app.repo import ScopedRepo


def require_session(repo: ScopedRepo, session_id: str) -> DebriefSession:
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    session_ctx.set(session_id)
    return session


def current_question(qs: list[DebriefQuestion]) -> DebriefQuestion | None:
    return next((q for q in qs if q.status == "asked"), None)
