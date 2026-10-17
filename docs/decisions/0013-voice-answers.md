# 0013 Voice answers: private audio, persisted transcription job, editable transcript
Status: accepted (slice 5)

**Context.** FR-3: the agent can record up to about 60 seconds instead of typing; the server transcribes it; the
transcript is shown inline and can be edited before it is used; transcription must not block the UI and must survive a
crash or a closed tab. Audio must not be publicly accessible. Agents do this many times a day, so the path must be quick.

**Decision.**
- Upload: `POST /v1/sessions/{id}/voice?question_id=...` with the raw audio as the body (no multipart dependency).
  The body is read with a hard cap (`MAX_AUDIO_BYTES`, default 2 MB) and never buffered past it. The real format is
  identified from the file's first bytes (webm, ogg, mp4, wav, mp3); the client's Content-Type is ignored. The upload
  is accepted only while the debrief is active and only for the current question. Limits: duration (`MAX_AUDIO_SECONDS`,
  the chat stops at 60 s) and notes per session.
- Job: each recording is a `voice_notes` row (queued, running, done, failed) with an attempt counter. Transcription runs
  in the background; the client polls `GET .../voice/{note_id}`. State is persisted, so a closed tab loses nothing.
  A note stuck in queued/running (the process died) is re-queued by the next poll; a failed note can be retried
  (at most 3 attempts), then the agent is told to type instead.
- Provider: a `Transcriber` interface (`app/stt/`) with a Gemini implementation (audio input via the same REST API
  and key as the LLM) and a clearly labelled `dev` stub that returns a fixed transcript so the flow can be tried without
  a key. `STT_PROVIDER=none` (default) disables voice; the debrief state carries `voice_enabled` so the chat only shows the
  microphone when it can work.
- The transcript is a draft. It goes into the text box; what the agent sends is the answer (and what extraction later
  quotes as evidence). The answer may carry `voice_note_id`; the message then records the note, the original transcript
  and whether the agent edited it, which is also a ready-made transcription-quality signal.
- Privacy: no endpoint serves audio. It lives only in the database and is deleted as soon as it is transcribed
  (kept only for a failed note, so it can be retried, or when `KEEP_AUDIO=true`). Audio and transcript text are never
  written to logs (sizes and ids only).
- Frontend: `MediaRecorder` with a format the browser supports (webm/opus, or mp4 on Safari), auto-stop at the limit,
  cancel, a blocked-microphone message, and the whole composer locked while recording or transcribing. A recording or
  transcript belongs to one question and is dropped if the question changes. The embedding page must allow the
  microphone: `<iframe allow="microphone">`. Recording needs HTTPS (or localhost).

**Alternatives.** Multipart upload (extra dependency, same result). Object storage for audio (more infrastructure;
the database is enough for a few hundred KB and keeps it private by construction). Streaming speech recognition over a
WebSocket (lower latency, much more complexity). The browser's built-in speech recognition (not available everywhere,
sends audio to an unknown service). Using the transcript without review (violates the edit requirement).

**Consequences.** The job is in-process with persisted state, like extraction (ADR 0010); the planned worker with a
jobs table will take over both. Gemini transcription and real microphone recording are untested here (see slice log);
accuracy on mixed Hindi and English speech is unknown. Audio larger than the cap is refused rather than split. Because
audio is deleted after success, a transcript cannot be re-run with a better model later.
