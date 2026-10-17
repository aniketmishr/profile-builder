"""Business rules. Talks only to ScopedRepo, never to raw queries."""
import math
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.ids import new_id
from app.logging import log, session_ctx
from app.models import DebriefSession, EndUser, ProfileFact
from app.repo import ScopedRepo
from app.schemas import FactIn, SessionCreate


# ---- session intake ---------------------------------------------------------
def _same_or_409(existing: DebriefSession, payload: SessionCreate) -> DebriefSession:
    if existing.task_id != payload.task.id or existing.end_user_id != payload.end_user.id:
        raise HTTPException(409, "idempotency_key already used for a different task or end user")
    return existing


def create_session(repo: ScopedRepo, payload: SessionCreate) -> tuple[DebriefSession, bool]:
    """Idempotent on (tenant_id, idempotency_key). Returns (session, created)."""
    if payload.tenant_id != repo.tenant_id:
        raise HTTPException(403, "tenant_id in body does not match the API key's tenant")

    existing = repo.get_session_by_key(payload.idempotency_key)
    if existing:
        session_ctx.set(existing.id)
        log("session intake: duplicate call, returning existing")
        return _same_or_409(existing, payload), False

    repo.upsert_agent(payload.agent.id, payload.agent.name)
    repo.upsert_end_user(payload.end_user.id, payload.end_user.display_name)
    try:
        row = repo.insert_session(
            id=new_id("ss"),
            agent_id=payload.agent.id,
            end_user_id=payload.end_user.id,
            idempotency_key=payload.idempotency_key,
            task_id=payload.task.id,
            task_context=payload.task.model_dump(),
            locale=payload.locale,
            status="created",
        )
    except IntegrityError:
        # Two concurrent calls with the same key: the unique constraint picked a winner.
        existing = repo.get_session_by_key(payload.idempotency_key)
        if existing is None:
            raise
        session_ctx.set(existing.id)
        log("session intake: lost insert race, returning existing")
        return _same_or_409(existing, payload), False

    repo.commit()
    session_ctx.set(row.id)
    log("session created", task_id=row.task_id, end_user_id=row.end_user_id, agent_id=row.agent_id)
    return row, True


# ---- fact writes ------------------------------------------------------------
def apply_facts(
    repo: ScopedRepo,
    end_user_id: str,
    source_session_id: str,
    facts: list[FactIn],
    provenance: dict,
    fact_provenance: dict[tuple[str, str], dict] | None = None,
    commit: bool = True,
) -> tuple[list[ProfileFact], list[ProfileFact], int]:
    """The ONE write path for facts (manual today, LLM extraction later).

    Conflict rule v1: the latest write for a key wins and supersedes the old row, which stays
    in history. Writing the same value again is a no-op. Duplicate keys inside one batch are
    collapsed first, keeping the highest confidence (later one wins ties).
    """
    end_user = repo.get_end_user(end_user_id, lock=True)  # serialises writers per profile
    if end_user is None:
        raise HTTPException(404, "end user not found")
    session = repo.get_session(source_session_id)
    if session is None:
        raise HTTPException(404, "source session not found")
    if session.end_user_id != end_user_id:
        raise HTTPException(422, "source session belongs to a different end user")
    session_ctx.set(session.id)

    batch: dict[tuple[str, str], FactIn] = {}
    for f in facts:
        k = (f.category, f.key)
        if k not in batch or f.confidence >= batch[k].confidence:
            batch[k] = f

    written: list[ProfileFact] = []
    unchanged: list[ProfileFact] = []
    for (category, key), f in batch.items():
        current = repo.current_fact(end_user_id, category, key)
        if current is not None and current.value == f.value:
            unchanged.append(current)
            continue
        new_id_ = new_id("ft")
        if current is not None:
            repo.supersede(current, new_id_)
        written.append(repo.add_fact(
            id=new_id_, end_user_id=end_user_id, source_session_id=source_session_id,
            category=category, key=key, value=f.value, confidence=f.confidence,
            evidence=f.evidence, is_current=True,
            provenance={**provenance, **(fact_provenance or {}).get((category, key), {})},
        ))
        log("fact saved", category=category, key=key, superseded=current is not None)

    if written:
        repo.touch_profile(end_user)
    if commit:
        repo.commit()
    else:
        repo.db.flush()
    return written, unchanged, end_user.profile_version


# ---- reads ------------------------------------------------------------------
def require_end_user(repo: ScopedRepo, end_user_id: str) -> EndUser:
    end_user = repo.get_end_user(end_user_id)
    if end_user is None:
        raise HTTPException(404, "end user not found")
    return end_user


CATEGORY_ORDER = [
    ("contact_preferences", "Contact"),
    ("constraints", "Constraints"),
    ("pain_points", "Pain points"),
    ("communication_style", "Style"),
    ("products_and_usage", "Products"),
    ("personal_context", "Context"),
    ("notes", "Notes"),
]


def _fmt_value(v) -> str:
    if isinstance(v, list):
        return ", ".join(_fmt_value(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k} {_fmt_value(x)}" for k, x in v.items())
    return str(v)


def _approx_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def build_context(end_user: EndUser, facts: list[ProfileFact], max_tokens: int | None) -> tuple[str, bool]:
    """Deterministic, LLM-free summary. Lowest-priority facts are dropped first to fit the budget."""
    name = end_user.display_name or end_user.id
    header = f"{name} ({end_user.id}):"
    if not facts:
        return f"{header} no profile facts captured yet.", False

    rank = {c: i for i, (c, _) in enumerate(CATEGORY_ORDER)}
    ordered = sorted(facts, key=lambda f: (rank.get(f.category, 99), -f.confidence, f.key))
    n_sessions = len({f.source_session_id for f in facts})
    updated = end_user.updated_at.strftime("%d %b %Y") if end_user.updated_at else "unknown date"
    footer = f"Last updated {updated} from {n_sessions} debrief session{'s' if n_sessions != 1 else ''}."
    labels = dict(CATEGORY_ORDER)

    def render(items: list[ProfileFact]) -> str:
        groups: dict[str, list[str]] = defaultdict(list)
        for f in items:
            groups[f.category].append(f"{f.key.replace('_', ' ')} {_fmt_value(f.value)}")
        body = " ".join(f"{labels.get(c, c)}: {'; '.join(v)}." for c, v in groups.items())
        return f"{header} {body} {footer}".strip()

    text = render(ordered)
    if max_tokens is None or _approx_tokens(text) <= max_tokens:
        return text, False
    for k in range(len(ordered) - 1, 0, -1):
        text = render(ordered[:k])
        if _approx_tokens(text) <= max_tokens:
            return text, True
    return render(ordered[:1]), True
