"""Voice answers: upload -> persisted transcription job -> editable transcript -> used as the typed answer.

Audio is private: nothing serves it, it lives only in the database, and it is deleted once transcribed
(unless KEEP_AUDIO is set or the job failed and may be retried). The transcript is only a draft: the agent
reviews and edits it, and what they send as the answer is what counts (and what extraction quotes).
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.config import get_settings
from app.db import open_session
from app.lookup import current_question as _current, require_session as _require_session
from app.logging import log, session_ctx
from app.models import VoiceNote
from app.repo import ScopedRepo
from app.schemas import VoiceNoteOut
from app.stt import Transcriber, TranscriptionError

MAX_ATTEMPTS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def sniff_audio_type(data: bytes) -> str | None:
    """Identify the file from its first bytes. The client's Content-Type is never trusted."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    return None


def to_out(note: VoiceNote) -> VoiceNoteOut:
    return VoiceNoteOut(
        id=note.id, status=note.status, question_id=note.question_id, transcript=note.transcript,
        error=note.error, attempt=note.attempt, size_bytes=note.size_bytes, duration_ms=note.duration_ms,
    )


def create_note(repo: ScopedRepo, session_id: str, question_id: str, data: bytes, duration_ms: int | None) -> VoiceNote:
    s = get_settings()
    _require_session(repo, session_id)
    debrief = repo.get_debrief(session_id)
    if debrief is None or debrief.state != "active":
        raise HTTPException(409, "the debrief is not active")
    current = _current(repo.debrief_questions(session_id))
    if current is None or current.id != question_id:
        raise HTTPException(409, "that question is no longer the current one")
    if not data:
        raise HTTPException(422, "empty recording")
    if len(data) > s.max_audio_bytes:
        raise HTTPException(413, "recording too large")
    mime = sniff_audio_type(data)
    if mime is None:
        raise HTTPException(415, "unsupported audio format (use webm, ogg, mp4, wav or mp3)")
    if duration_ms is not None and duration_ms > s.max_audio_seconds * 1000:
        raise HTTPException(422, f"recording too long (max {s.max_audio_seconds} seconds)")
    if repo.count_voice_notes(session_id) >= s.max_voice_notes_per_session:
        raise HTTPException(429, "too many voice notes for this session")
    note = repo.create_voice_note(
        session_id, question_id=question_id, status="queued", attempt=1, mime_type=mime,
        size_bytes=len(data), duration_ms=duration_ms, audio=data,
    )
    repo.commit()
    log("voice note queued", note_id=note.id, size_bytes=len(data), mime=mime)
    return note


def get_note(repo: ScopedRepo, session_id: str, note_id: str) -> tuple[VoiceNote, bool]:
    """Returns (note, requeued). A queued/running note that has gone quiet (the process died) is re-queued."""
    _require_session(repo, session_id)
    note = repo.get_voice_note(note_id, session_id, lock=True)
    if note is None:
        raise HTTPException(404, "voice note not found")
    quiet_for = _now() - _aware(note.started_at or note.created_at)
    if note.status in ("queued", "running") and quiet_for > timedelta(seconds=get_settings().voice_stale_seconds) \
            and note.audio is not None and note.attempt < MAX_ATTEMPTS:
        note.status, note.attempt, note.started_at = "queued", note.attempt + 1, _now()
        repo.commit()
        return note, True
    repo.commit()  # release the row lock
    return note, False


def retry(repo: ScopedRepo, session_id: str, note_id: str) -> VoiceNote:
    _require_session(repo, session_id)
    note = repo.get_voice_note(note_id, session_id, lock=True)
    if note is None:
        raise HTTPException(404, "voice note not found")
    if note.status != "failed" or note.audio is None:
        raise HTTPException(409, "only a failed note that still has its recording can be retried")
    if note.attempt >= MAX_ATTEMPTS:
        raise HTTPException(409, "too many attempts; please record again or type your answer")
    note.status, note.attempt, note.error, note.started_at = "queued", note.attempt + 1, None, _now()
    repo.commit()
    return note


def _fail(repo: ScopedRepo, note: VoiceNote, message: str) -> None:
    note.status, note.error, note.finished_at = "failed", message[:300], _now()  # audio kept so it can be retried
    repo.commit()
    log("voice transcription failed", note_id=note.id, error=message[:200])


def run_transcription(tenant_id: str, note_id: str, transcriber: Transcriber | None) -> None:
    """Background entry point. Never raises: any failure is recorded on the note, which the client sees by polling."""
    db = open_session()
    repo = ScopedRepo(db, tenant_id)
    try:
        note = repo.get_voice_note(note_id, lock=True)
        if note is None or note.status != "queued":
            return  # someone else has it, or it is already finished
        session_ctx.set(note.session_id)
        if transcriber is None:
            _fail(repo, note, "voice transcription is not configured")
            return
        note.status, note.started_at = "running", _now()
        repo.commit()
        session = repo.get_session(note.session_id)
        try:
            text = transcriber.transcribe(
                note.audio or b"", note.mime_type, session.locale if session else None,
                get_settings().stt_timeout_seconds)
        except TranscriptionError as e:
            _fail(repo, note, str(e))
            return
        note.transcript, note.status, note.error = text, "done", None
        note.provider, note.model, note.finished_at = transcriber.name, transcriber.model, _now()
        if not get_settings().keep_audio:
            note.audio = None
        repo.commit()
        log("voice transcription done", note_id=note.id, chars=len(text), provider=transcriber.name)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        try:
            note = repo.get_voice_note(note_id, lock=True)
            if note is not None and note.status in ("queued", "running"):
                _fail(repo, note, f"unexpected error: {type(e).__name__}")
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()


def use_in_answer(repo: ScopedRepo, session_id: str, question_id: str, note_id: str, final_text: str) -> dict:
    """Validate a voice note being used as the answer to `question_id` and return audit info for the message."""
    note = repo.get_voice_note(note_id, session_id)
    if note is None or note.question_id != question_id or note.status != "done":
        raise HTTPException(422, "that voice note can't be used for this question")
    note.used_at = _now()
    original = " ".join((note.transcript or "").split())
    return {"voice_note_id": note.id, "transcript": note.transcript, "edited": " ".join(final_text.split()) != original}
