import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import voice
from app.config import get_settings
from app.db import open_session
from app.main import app
from app.repo import ScopedRepo
from app.stt import TranscriptionError, get_transcriber
from app.stt.dev import DevTranscriber
from app.stt.gemini import GeminiTranscriber
from tests.test_debrief import H, answer, start

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 200


class ScriptedSTT:
    """Test double: returns queued transcripts (or raises queued exceptions) and records the calls."""
    name, model = "scripted", "stt-test"

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[bytes, str, str | None]] = []

    def transcribe(self, audio, mime_type, language=None, timeout=None):
        self.calls.append((audio, mime_type, language))
        r = self.results.pop(0) if self.results else "default transcript"
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def with_stt():
    def _set(provider):
        app.dependency_overrides[get_transcriber] = lambda: provider
    yield _set
    app.dependency_overrides.pop(get_transcriber, None)


def upload(client, keys, sid, qid, data=WEBM, tenant="tn_a", duration=4000, headers=None):
    return client.post(f"/v1/sessions/{sid}/voice?question_id={qid}&duration_ms={duration}", content=data,
                       headers={**H(keys, tenant), "Content-Type": "audio/webm", **(headers or {})})


def note_state(client, keys, sid, nid, tenant="tn_a"):
    return client.get(f"/v1/sessions/{sid}/voice/{nid}", headers=H(keys, tenant))


def db_note(nid, tenant="tn_a"):
    db = open_session()
    return db, ScopedRepo(db, tenant).get_voice_note(nid)


def active(client, keys, make_session, task, user="eu_1"):
    sid = make_session("tn_a", task, user=user)
    return sid, start(client, keys, sid)


# ---- availability -------------------------------------------------------------------------
def test_voice_is_off_without_a_provider(client, keys, make_session, with_stt):
    with_stt(None)
    sid, st = active(client, keys, make_session, "task_v_off")
    assert st["voice_enabled"] is False
    assert upload(client, keys, sid, st["current_question_id"]).status_code == 503


def test_voice_enabled_flag_follows_the_provider(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT())
    sid, st = active(client, keys, make_session, "task_v_on")
    assert st["voice_enabled"] is True
    assert client.get(f"/v1/sessions/{sid}/debrief", headers=H(keys)).json()["voice_enabled"] is True


# ---- the job ----------------------------------------------------------------------------------
def test_upload_transcribes_in_the_background_and_deletes_the_audio(client, keys, make_session, with_stt):
    stt = ScriptedSTT("he said only whatsapp")
    with_stt(stt)
    sid, st = active(client, keys, make_session, "task_v_happy")
    r = upload(client, keys, sid, st["current_question_id"])
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["size_bytes"] == len(WEBM)
    out = note_state(client, keys, sid, r.json()["id"]).json()
    assert out["status"] == "done" and out["transcript"] == "he said only whatsapp" and out["error"] is None
    assert stt.calls == [(WEBM, "audio/webm", "en-IN")]  # the sniffed type and the session locale reach the provider
    db, row = db_note(r.json()["id"])
    try:
        assert row.audio is None and row.provider == "scripted" and row.model == "stt-test"  # audio is not kept
    finally:
        db.close()


def test_keep_audio_setting_keeps_the_recording(client, keys, make_session, with_stt, monkeypatch):
    monkeypatch.setattr(get_settings(), "keep_audio", True)
    with_stt(ScriptedSTT("hello"))
    sid, st = active(client, keys, make_session, "task_v_keep")
    nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    db, row = db_note(nid)
    try:
        assert row.audio == WEBM
    finally:
        db.close()


def test_no_endpoint_serves_the_audio(client, keys, make_session, with_stt, monkeypatch):
    monkeypatch.setattr(get_settings(), "keep_audio", True)
    with_stt(ScriptedSTT("hello"))
    sid, st = active(client, keys, make_session, "task_v_private")
    nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    body = note_state(client, keys, sid, nid).json()
    assert "audio" not in body and set(body) == {"id", "status", "question_id", "transcript", "error", "attempt", "size_bytes", "duration_ms"}
    for path in (f"/v1/sessions/{sid}/voice/{nid}/audio", f"/v1/voice/{nid}", f"/audio/{nid}"):
        assert client.get(path, headers=H(keys)).status_code == 404


def test_transcript_text_is_never_logged(client, keys, make_session, with_stt, caplog):
    secret = "customer card number is four two four two"
    with_stt(ScriptedSTT(secret))
    sid, st = active(client, keys, make_session, "task_v_log")
    with caplog.at_level(logging.INFO, logger="app"):
        nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
        note_state(client, keys, sid, nid)
    assert caplog.records and not any(secret in r.getMessage() or secret in str(getattr(r, "extra_fields", "")) for r in caplog.records)


# ---- validation --------------------------------------------------------------------------------------
def test_upload_validation(client, keys, make_session, with_stt, monkeypatch):
    with_stt(ScriptedSTT())
    sid, st = active(client, keys, make_session, "task_v_valid")
    qid = st["current_question_id"]
    assert upload(client, keys, sid, qid, data=b"").status_code == 422
    assert upload(client, keys, sid, qid, data=b"this is not audio at all").status_code == 415
    assert upload(client, keys, sid, qid, data=b"%PDF-1.4 fake").status_code == 415  # the declared type is never trusted
    assert upload(client, keys, sid, qid, duration=76_000).status_code == 422
    assert upload(client, keys, sid, "dq_wrong").status_code == 409
    monkeypatch.setattr(get_settings(), "max_audio_bytes", 100)
    assert upload(client, keys, sid, qid).status_code == 413  # declared Content-Length is already too big


def test_oversized_chunked_upload_is_cut_off(client, keys, make_session, with_stt, monkeypatch):
    with_stt(ScriptedSTT())
    sid, st = active(client, keys, make_session, "task_v_chunked")
    monkeypatch.setattr(get_settings(), "max_audio_bytes", 1000)

    def chunks():  # no Content-Length: the server must stop reading on its own
        yield WEBM
        for _ in range(20):
            yield b"\x00" * 500

    r = client.post(f"/v1/sessions/{sid}/voice?question_id={st['current_question_id']}",
                    content=chunks(), headers={**H(keys), "Content-Type": "audio/webm"})
    assert r.status_code == 413


def test_upload_needs_an_active_debrief_and_the_current_question(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT())
    sid = make_session("tn_a", "task_v_state")
    assert upload(client, keys, sid, "dq_x").status_code == 409  # not started
    st = start(client, keys, sid)
    first = st["current_question_id"]
    st = answer(client, keys, sid, st, "typed answer")
    assert upload(client, keys, sid, first).status_code == 409  # that question has moved on
    while st["state"] == "active":
        st = answer(client, keys, sid, st, action="skip", text=None)
    assert upload(client, keys, sid, first).status_code == 409  # complete


def test_per_session_cap(client, keys, make_session, with_stt, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_voice_notes_per_session", 2)
    with_stt(ScriptedSTT())
    sid, st = active(client, keys, make_session, "task_v_cap")
    assert [upload(client, keys, sid, st["current_question_id"]).status_code for _ in range(3)] == [202, 202, 429]


# ---- failure, retry, crash, stale -----------------------------------------------------------------------
def test_failed_transcription_keeps_the_audio_and_can_be_retried(client, keys, make_session, with_stt):
    stt = ScriptedSTT(TranscriptionError("no speech detected in the recording"), "second time works")
    with_stt(stt)
    sid, st = active(client, keys, make_session, "task_v_retry")
    nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    out = note_state(client, keys, sid, nid).json()
    assert out["status"] == "failed" and "no speech" in out["error"]
    db, row = db_note(nid)
    try:
        assert row.audio == WEBM  # kept so a retry is possible
    finally:
        db.close()
    r = client.post(f"/v1/sessions/{sid}/voice/{nid}/retry", headers=H(keys))
    assert r.status_code == 202 and r.json()["attempt"] == 2
    out = note_state(client, keys, sid, nid).json()
    assert out["status"] == "done" and out["transcript"] == "second time works" and out["error"] is None
    assert client.post(f"/v1/sessions/{sid}/voice/{nid}/retry", headers=H(keys)).status_code == 409  # done: nothing to retry


def test_retries_are_limited(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT(*[TranscriptionError("provider down")] * 5))
    sid, st = active(client, keys, make_session, "task_v_limit")
    nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    codes = [client.post(f"/v1/sessions/{sid}/voice/{nid}/retry", headers=H(keys)).status_code for _ in range(3)]
    assert codes == [202, 202, 409]  # attempt 1 + two retries, then it asks the agent to type instead


def test_unexpected_crash_marks_the_note_failed(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT(RuntimeError("boom"), "recovered"))
    sid, st = active(client, keys, make_session, "task_v_crash")
    nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    out = note_state(client, keys, sid, nid).json()
    assert out["status"] == "failed" and out["error"] == "unexpected error: RuntimeError"
    client.post(f"/v1/sessions/{sid}/voice/{nid}/retry", headers=H(keys))
    assert note_state(client, keys, sid, nid).json()["status"] == "done"


def test_a_stuck_job_is_requeued_by_polling_but_a_fresh_one_is_left_alone(client, keys, make_session, with_stt):
    stt = ScriptedSTT("recovered after restart")
    with_stt(stt)
    sid, st = active(client, keys, make_session, "task_v_stale")
    qid = st["current_question_id"]
    nid = upload(client, keys, sid, qid).json()["id"]  # done once...
    db, row = db_note(nid)
    row.status, row.audio, row.transcript, row.started_at = "running", WEBM, None, datetime.now(timezone.utc)
    db.commit()
    calls = len(stt.calls)
    assert note_state(client, keys, sid, nid).json()["status"] == "running" and len(stt.calls) == calls  # fresh: untouched

    row = ScopedRepo(db, "tn_a").get_voice_note(nid)
    row.started_at = datetime.now(timezone.utc) - timedelta(hours=1)  # the process presumably died
    db.commit()
    db.close()
    out = note_state(client, keys, sid, nid).json()
    assert out["attempt"] == 2 and note_state(client, keys, sid, nid).json()["status"] == "done"
    assert len(stt.calls) == calls + 1


# ---- using the transcript as the answer -----------------------------------------------------------------------
def test_answer_records_that_it_came_from_a_voice_note_and_whether_it_was_edited(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT("he wants whatsapp not email", "second recording"))
    sid, st = active(client, keys, make_session, "task_v_use")
    n1 = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    st = answer_with(client, keys, sid, st, "he wants WhatsApp, not email", n1)  # the agent fixed the casing
    n2 = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    answer_with(client, keys, sid, st, "second recording", n2)  # used as transcribed
    db = open_session()
    try:
        voices = [m.meta["voice"] for m in ScopedRepo(db, "tn_a").debrief_messages(sid) if m.role == "agent"]
        assert [v["edited"] for v in voices] == [True, False]
        assert voices[0]["voice_note_id"] == n1 and voices[0]["transcript"] == "he wants whatsapp not email"
        assert ScopedRepo(db, "tn_a").get_voice_note(n1).used_at is not None
    finally:
        db.close()


def answer_with(client, keys, sid, state, text, note_id, tenant="tn_a", expect=200):
    r = client.post(f"/v1/sessions/{sid}/debrief/answer", headers=H(keys, tenant),
                    json={"question_id": state["current_question_id"], "text": text, "voice_note_id": note_id})
    assert r.status_code == expect, r.text
    return r.json()


def test_a_voice_note_cannot_be_used_for_the_wrong_question_or_before_it_is_done(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT("first", TranscriptionError("nope")))
    sid, st = active(client, keys, make_session, "task_v_misuse")
    done = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    failed = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    answer_with(client, keys, sid, st, "x", failed, expect=422)  # not transcribed
    answer_with(client, keys, sid, st, "x", "vn_unknown", expect=422)
    st2 = answer(client, keys, sid, st, "typed")  # moves to the next question
    answer_with(client, keys, sid, st2, "x", done, expect=422)  # the note belongs to the previous question


def test_a_note_from_another_session_cannot_be_used(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT("other session words"))
    sid_a, st_a = active(client, keys, make_session, "task_v_sa", user="eu_v1")
    sid_b, st_b = active(client, keys, make_session, "task_v_sb", user="eu_v2")
    nid = upload(client, keys, sid_a, st_a["current_question_id"]).json()["id"]
    answer_with(client, keys, sid_b, st_b, "x", nid, expect=422)


# ---- isolation and token scope ----------------------------------------------------------------------------------
def test_other_tenant_cannot_use_or_see_voice_notes(client, keys, make_session, with_stt):
    with_stt(ScriptedSTT("private words"))
    sid, st = active(client, keys, make_session, "task_v_iso")
    nid = upload(client, keys, sid, st["current_question_id"]).json()["id"]
    assert note_state(client, keys, sid, nid, "tn_b").status_code == 404
    assert upload(client, keys, sid, st["current_question_id"], tenant="tn_b").status_code == 404
    assert client.post(f"/v1/sessions/{sid}/voice/{nid}/retry", headers=H(keys, "tn_b")).status_code == 404


def test_session_token_can_record_but_only_for_its_own_session(client, keys, with_stt):
    with_stt(ScriptedSTT("token words"))
    def new(key):
        body = {"idempotency_key": key, "tenant_id": "tn_a", "agent": {"id": "ag_1"}, "end_user": {"id": "eu_v3"},
                "task": {"id": key, "type": "refund"}}
        d = client.post("/v1/sessions", headers=H(keys), json=body).json()
        return d["session_id"], {"X-Session-Token": d["chat_url"].split("token=")[1]}
    sid1, t1 = new("vtok1")
    sid2, _ = new("vtok2")
    st = client.post(f"/v1/sessions/{sid1}/debrief/start", headers=t1).json()
    r = client.post(f"/v1/sessions/{sid1}/voice?question_id={st['current_question_id']}", content=WEBM,
                    headers={**t1, "Content-Type": "audio/webm"})
    assert r.status_code == 202
    nid = r.json()["id"]
    assert client.get(f"/v1/sessions/{sid1}/voice/{nid}", headers=t1).json()["transcript"] == "token words"
    assert client.get(f"/v1/sessions/{sid2}/voice/{nid}", headers=t1).status_code == 404  # token is bound to sid1
    assert client.post(f"/v1/sessions/{sid2}/voice?question_id=x", content=WEBM, headers={**t1, "Content-Type": "audio/webm"}).status_code == 404


# ---- providers and helpers -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("head,expected", [
    (b"\x1a\x45\xdf\xa3rest", "audio/webm"), (b"OggSrest", "audio/ogg"), (b"\x00\x00\x00\x20ftypM4A ", "audio/mp4"),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav"), (b"ID3\x04rest", "audio/mpeg"), (b"\xff\xfbrest", "audio/mpeg"),
    (b"%PDF-1.4", None), (b"", None), (b"MZ\x90\x00", None),
])
def test_sniff_audio_type(head, expected):
    assert voice.sniff_audio_type(head) == expected


def _gemini(handler):
    return GeminiTranscriber("secret-key", "some-model", client=httpx.Client(transport=httpx.MockTransport(handler)))


def _ok(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_gemini_transcriber_request_shape_and_parsing():
    import base64, json
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers.get("x-goog-api-key"), body=json.loads(request.content))
        return _ok("  ```\nhello there\n```  ")

    assert _gemini(handler).transcribe(b"AUDIO", "audio/webm", "en-IN") == "hello there"
    assert seen["url"].endswith("/models/some-model:generateContent") and "secret-key" not in seen["url"]
    assert seen["key"] == "secret-key"
    parts = seen["body"]["contents"][0]["parts"]
    assert "en-IN" in parts[0]["text"] and "Do not translate" in parts[0]["text"]
    assert parts[1]["inline_data"] == {"mime_type": "audio/webm", "data": base64.b64encode(b"AUDIO").decode()}


@pytest.mark.parametrize("reply", ["NO_SPEECH", " no_speech. ", "   "])
def test_gemini_transcriber_reports_silence(reply):
    with pytest.raises(TranscriptionError, match="no speech"):
        _gemini(lambda r: _ok(reply)).transcribe(b"x", "audio/webm")


def test_gemini_transcriber_failures(monkeypatch):
    monkeypatch.setattr("app.stt.gemini.time.sleep", lambda s: None)
    codes = iter([503, 200])
    assert _gemini(lambda r: httpx.Response(next(codes), json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})).transcribe(b"x", "audio/webm") == "ok"
    n = {"c": 0}

    def bad(request):
        n["c"] += 1
        return httpx.Response(400, json={})

    with pytest.raises(TranscriptionError, match="http 400"):
        _gemini(bad).transcribe(b"x", "audio/webm")
    assert n["c"] == 1  # client errors are not retried
    with pytest.raises(TranscriptionError):
        _gemini(lambda r: httpx.Response(200, json={"candidates": []})).transcribe(b"x", "audio/webm")
    with pytest.raises(ValueError):
        GeminiTranscriber("", "m")


def test_dev_transcriber_and_provider_selection(monkeypatch):
    assert "stub transcript" in DevTranscriber().transcribe(b"x", "audio/webm")
    with pytest.raises(TranscriptionError):
        DevTranscriber().transcribe(b"", "audio/webm")
    settings = get_settings()
    get_transcriber.cache_clear()
    try:
        assert get_transcriber() is None  # default: voice off
        for provider, check in (("dev", lambda t: isinstance(t, DevTranscriber)), ("nonsense", None)):
            monkeypatch.setattr(settings, "stt_provider", provider)
            get_transcriber.cache_clear()
            if check:
                assert check(get_transcriber())
            else:
                with pytest.raises(ValueError):
                    get_transcriber()
        monkeypatch.setattr(settings, "stt_provider", "gemini")
        monkeypatch.setattr(settings, "gemini_api_key", "")
        get_transcriber.cache_clear()
        with pytest.raises(ValueError):
            get_transcriber()
    finally:
        monkeypatch.undo()
        get_transcriber.cache_clear()
