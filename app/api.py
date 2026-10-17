from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from app import debrief, extraction, planner, services, voice
from app.config import get_settings
from app.deps import get_debrief_repo, get_repo
from app.llm import LLMProvider, get_llm
from app.stt import Transcriber, get_transcriber
from app.models import DebriefSession
from app.repo import ScopedRepo
from app.schemas import (
    AnswerIn, ConfirmIn, ConfirmOut, ContextOut, DebriefStateOut, ExtractionOut, FactHistory, FactOut, FactsIn, FactsWritten, HistoryOut, PlanPreviewOut,
    PlannedQuestionOut, ProfileOut, SessionCreate, SessionOut, SessionRef, VoiceNoteOut,
)
from app.security import make_session_token

router = APIRouter(prefix="/v1")
debug_router = APIRouter(prefix="/v1", tags=["dev"])


def _with_voice(state: DebriefStateOut, stt: Transcriber | None) -> DebriefStateOut:
    state.voice_enabled = stt is not None  # lets the chat decide whether to show the microphone
    return state


def _session_out(row: DebriefSession, created: bool) -> SessionOut:
    token = make_session_token(row.id, row.tenant_id)
    base = get_settings().public_base_url.rstrip("/")
    return SessionOut(
        session_id=row.id, status=row.status, created=created,
        chat_url=f"{base}/chat/{row.id}?token={token}",
        tenant_id=row.tenant_id, agent_id=row.agent_id, end_user_id=row.end_user_id,
        task_id=row.task_id, created_at=row.created_at,
    )


@router.get("/whoami", tags=["ops"])
def whoami(repo: ScopedRepo = Depends(get_repo)):
    """Which tenant does this API key belong to? (Used by the mock admin panel.)"""
    return {"tenant_id": repo.tenant_id}


# ---- sessions ---------------------------------------------------------------
@router.post(
    "/sessions", response_model=SessionOut, tags=["sessions"],
    status_code=201,
    responses={200: {"description": "Same idempotency_key seen before: existing session returned"},
               403: {"description": "tenant_id in body differs from the API key's tenant"},
               409: {"description": "idempotency_key reused for a different task or end user"}},
)
def create_session(
    payload: SessionCreate, response: Response, background: BackgroundTasks,
    repo: ScopedRepo = Depends(get_repo), llm: LLMProvider | None = Depends(get_llm),
):
    """Called by the admin panel when a task closes. Idempotent on `idempotency_key`."""
    row, created = services.create_session(repo, payload)
    response.status_code = 201 if created else 200
    if created and get_settings().precompute_plans:
        # Best effort: have the question plan ready before the agent opens the chat.
        background.add_task(debrief.precompute_plan, repo.tenant_id, row.id, llm)
    return _session_out(row, created)


@router.get("/sessions/{session_id}", response_model=SessionOut, tags=["sessions"])
def get_session(session_id: str, repo: ScopedRepo = Depends(get_repo)):
    row = repo.get_session(session_id)
    if row is None:
        raise HTTPException(404, "session not found")
    return _session_out(row, False)


# ---- debrief conversation (API key OR session token) ------------------------
@router.post("/sessions/{session_id}/debrief/start", response_model=DebriefStateOut, tags=["debrief"])
def start_debrief(
    session_id: str,
    repo: ScopedRepo = Depends(get_debrief_repo),
    llm: LLMProvider | None = Depends(get_llm),
    stt: Transcriber | None = Depends(get_transcriber),
):
    """Open the debrief: creates the plan if needed and posts the intro and first question. Idempotent."""
    return _with_voice(debrief.start(repo, session_id, llm), stt)


@router.get("/sessions/{session_id}/debrief", response_model=DebriefStateOut, tags=["debrief"])
def get_debrief(
    session_id: str, repo: ScopedRepo = Depends(get_debrief_repo),
    stt: Transcriber | None = Depends(get_transcriber),
):
    """Current conversation state: messages, question statuses, progress. Safe to poll or reload."""
    return _with_voice(debrief.get_state(repo, session_id), stt)


@router.post(
    "/sessions/{session_id}/debrief/answer", response_model=DebriefStateOut, tags=["debrief"],
    responses={409: {"description": "Debrief complete, not started, or `question_id` is not the current question"}},
)
def answer_debrief(
    session_id: str, body: AnswerIn, background: BackgroundTasks,
    repo: ScopedRepo = Depends(get_debrief_repo),
    llm: LLMProvider | None = Depends(get_llm),
    stt: Transcriber | None = Depends(get_transcriber),
):
    """Answer, skip, or end the debrief. Returns the updated state including the AI's next message.
    When the debrief completes, extraction starts in the background (poll `GET .../extraction`).
    Set `voice_note_id` when `text` came from a voice note's (possibly edited) transcript."""
    state = _with_voice(debrief.submit(repo, llm, session_id, body), stt)
    if state.state == "complete" and get_settings().auto_extract:
        _, should_run = extraction.request(repo, session_id, force=False)
        if should_run:
            background.add_task(extraction.run_extraction, repo.tenant_id, session_id, llm)
    return state


# ---- voice answers (API key OR session token) ------------------------------------------------
AUDIO_BODY = {"requestBody": {"required": True, "content": {
    t: {"schema": {"type": "string", "format": "binary"}}
    for t in ("audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/mpeg")}}}


async def _read_capped(request: Request, cap: int) -> bytes:
    """Read the body but stop as soon as it exceeds the cap (never buffer an unbounded upload)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise HTTPException(413, "recording too large")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > cap:
            raise HTTPException(413, "recording too large")
    return bytes(buf)


@router.post(
    "/sessions/{session_id}/voice", response_model=VoiceNoteOut, status_code=202, tags=["voice"],
    openapi_extra=AUDIO_BODY,
    responses={409: {"description": "Debrief not active, or `question_id` is not the current question"},
               413: {"description": "Recording too large"}, 415: {"description": "Not a supported audio format"},
               429: {"description": "Too many voice notes for this session"},
               503: {"description": "Voice transcription is not configured"}},
)
async def upload_voice(
    session_id: str, request: Request, background: BackgroundTasks,
    question_id: str = Query(..., description="the current question being answered"),
    duration_ms: int | None = Query(None, ge=0),
    repo: ScopedRepo = Depends(get_debrief_repo),
    stt: Transcriber | None = Depends(get_transcriber),
):
    """Upload a recorded answer (raw audio bytes as the request body). Transcription runs in the background:
    poll `GET .../voice/{note_id}` until `status` is `done` or `failed`."""
    if stt is None:
        raise HTTPException(503, "voice transcription is not configured")
    data = await _read_capped(request, get_settings().max_audio_bytes)
    note = await run_in_threadpool(voice.create_note, repo, session_id, question_id, data, duration_ms)
    background.add_task(voice.run_transcription, repo.tenant_id, note.id, stt)
    return voice.to_out(note)


@router.get("/sessions/{session_id}/voice/{note_id}", response_model=VoiceNoteOut, tags=["voice"])
def get_voice_note(
    session_id: str, note_id: str, background: BackgroundTasks,
    repo: ScopedRepo = Depends(get_debrief_repo),
    stt: Transcriber | None = Depends(get_transcriber),
):
    """Poll a voice note. The transcript is a draft: show it to the agent to edit before it is used as the answer.
    A note stuck in queued/running (the process died) is re-queued by this call."""
    note, requeued = voice.get_note(repo, session_id, note_id)
    if requeued:
        background.add_task(voice.run_transcription, repo.tenant_id, note.id, stt)
    return voice.to_out(note)


@router.post("/sessions/{session_id}/voice/{note_id}/retry", response_model=VoiceNoteOut, status_code=202, tags=["voice"],
             responses={409: {"description": "Only a failed note that still has its recording can be retried"}})
def retry_voice_note(
    session_id: str, note_id: str, background: BackgroundTasks,
    repo: ScopedRepo = Depends(get_debrief_repo),
    stt: Transcriber | None = Depends(get_transcriber),
):
    note = voice.retry(repo, session_id, note_id)
    background.add_task(voice.run_transcription, repo.tenant_id, note.id, stt)
    return voice.to_out(note)


# ---- extraction + confirm (API key OR session token) -------------------------------------
@router.post(
    "/sessions/{session_id}/extraction", response_model=ExtractionOut, status_code=202, tags=["extraction"],
    responses={409: {"description": "Debrief not complete, or facts already confirmed"}},
)
def start_extraction(
    session_id: str, background: BackgroundTasks,
    repo: ScopedRepo = Depends(get_debrief_repo),
    llm: LLMProvider | None = Depends(get_llm),
):
    """(Re)run extraction for a completed debrief, e.g. a retry. It normally starts by itself when the debrief
    completes. Does nothing if a run is already in progress; refused once the facts are confirmed."""
    _, should_run = extraction.request(repo, session_id, force=True)
    if should_run:
        background.add_task(extraction.run_extraction, repo.tenant_id, session_id, llm)
    return extraction.get_out(repo, session_id)


@router.get("/sessions/{session_id}/extraction", response_model=ExtractionOut, tags=["extraction"])
def get_extraction(session_id: str, repo: ScopedRepo = Depends(get_debrief_repo)):
    """Proposed facts with their evidence quotes. Poll while `status` is `running`."""
    return extraction.get_out(repo, session_id)


@router.post(
    "/sessions/{session_id}/extraction/confirm", response_model=ConfirmOut, tags=["extraction"],
    responses={409: {"description": "Not ready yet, or already confirmed"}, 422: {"description": "Bad decision"}},
)
def confirm_extraction(session_id: str, body: ConfirmIn, repo: ScopedRepo = Depends(get_debrief_repo)):
    """Save the facts into the profile. Facts you don't list are kept; use `discard` or `edit` to change them."""
    return extraction.confirm(repo, session_id, body)


# ---- profiles ---------------------------------------------------------------
@router.get("/profiles/{end_user_id}", response_model=ProfileOut, tags=["profiles"])
def get_profile(end_user_id: str, repo: ScopedRepo = Depends(get_repo)):
    """Merged view: the current value of every fact. No LLM on this path."""
    eu = services.require_end_user(repo, end_user_id)
    facts = repo.current_facts(end_user_id)
    return ProfileOut(
        end_user_id=eu.id, tenant_id=eu.tenant_id, display_name=eu.display_name,
        profile_version=eu.profile_version, updated_at=eu.updated_at,
        facts=[FactOut.model_validate(f) for f in facts],
    )


@router.get("/profiles/{end_user_id}/history", response_model=HistoryOut, tags=["profiles"])
def get_history(end_user_id: str, repo: ScopedRepo = Depends(get_repo)):
    """Every version of every fact (oldest first) plus the sessions they came from."""
    eu = services.require_end_user(repo, end_user_id)
    facts = repo.all_facts(end_user_id)
    grouped: dict[tuple[str, str], list[FactOut]] = {}
    for f in facts:
        grouped.setdefault((f.category, f.key), []).append(FactOut.model_validate(f))
    sessions = repo.sessions_by_ids({f.source_session_id for f in facts})
    return HistoryOut(
        end_user_id=eu.id, tenant_id=eu.tenant_id,
        history=[FactHistory(category=c, key=k, versions=v) for (c, k), v in grouped.items()],
        sessions=[SessionRef(
            session_id=s.id, task_id=s.task_id, task_type=s.task_context.get("type"),
            task_title=s.task_context.get("title"), agent_id=s.agent_id, created_at=s.created_at,
        ) for s in sessions],
    )


@router.get(
    "/profiles/{end_user_id}/context", tags=["profiles"],
    response_model=ContextOut, responses={200: {"content": {"text/plain": {}}}},
)
def get_context(
    end_user_id: str,
    max_tokens: int | None = Query(None, ge=20, le=4000, description="Approximate token budget"),
    format: Literal["json", "text"] = "json",
    repo: ScopedRepo = Depends(get_repo),
):
    """LLM-ready text block, built deterministically from current facts."""
    eu = services.require_end_user(repo, end_user_id)
    text, truncated = services.build_context(eu, repo.current_facts(end_user_id), max_tokens)
    if format == "text":
        return PlainTextResponse(text)
    return ContextOut(end_user_id=eu.id, context=text, approx_tokens=(len(text) + 3) // 4, truncated=truncated)


# ---- dev only: write facts by hand (day 2 replaces this caller with the extractor) -------------
@debug_router.post("/profiles/{end_user_id}/facts", response_model=FactsWritten)
def write_facts(end_user_id: str, body: FactsIn, repo: ScopedRepo = Depends(get_repo)):
    """Enabled only when ENABLE_DEBUG_ENDPOINTS=true. Uses the same write path as extraction will."""
    written, unchanged, version = services.apply_facts(
        repo, end_user_id, body.source_session_id, body.facts, provenance={"origin": "manual"},
    )
    return FactsWritten(
        written=[FactOut.model_validate(f) for f in written],
        unchanged=[FactOut.model_validate(f) for f in unchanged],
        profile_version=version,
    )


@debug_router.post("/sessions/{session_id}/plan-preview", response_model=PlanPreviewOut)
def plan_preview(
    session_id: str,
    repo: ScopedRepo = Depends(get_repo),
    llm: LLMProvider | None = Depends(get_llm),
):
    """Dev only: generate the debrief question plan for a session (one LLM call, nothing is saved).

    Shows which provider/model/prompt version produced it, and whether the fallback was used.
    """
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    end_user = repo.get_end_user(session.end_user_id)
    agent = repo.get_agent(session.agent_id)
    inp = planner.PlanInput(
        task=session.task_context,
        end_user_name=end_user.display_name if end_user else "",
        agent_name=agent.name if agent else "",
        locale=session.locale,
        known_facts=[(f.category, f.key, f.value) for f in repo.current_facts(session.end_user_id)],
    )
    result = planner.plan_questions(llm, inp)
    return PlanPreviewOut(
        session_id=session.id, source=result.source,
        provider=getattr(llm, "name", None), model=result.model,
        prompt_version=result.prompt_version, latency_ms=result.latency_ms, error=result.error,
        intro=planner.intro_text(inp, len(result.questions)),
        questions=[PlannedQuestionOut(**q.model_dump()) for q in result.questions],
    )
