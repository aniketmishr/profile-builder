# Slice log

Each slice is a small, shippable change. For every slice: goal, decisions (ADRs), what changed, how to verify.

## Slice 0: Day 1 foundation
- **Goal:** data model, session intake, profile store, retrieval API, deployable.
- **ADRs:** 0001 to 0005.
- **Verify:** `pytest -q`; `python -m scripts.smoke` against a running server.

## Slice 1: LLM layer and question planner
- **Goal:** provider-agnostic LLM interface and a task-aware debrief question plan with a safe fallback.
- **ADRs:** 0006, 0007.
- **Changed:** `app/llm/*`, `app/planner.py`, `app/prompts/planner_v1.md`, config, dev endpoint
  `POST /v1/sessions/{id}/plan-preview`, `tests/test_planner.py`.
- **Verify:** `pytest -q` (37 tests). With a key set (`LLM_PROVIDER=gemini`, `LLM_MODEL`, `GEMINI_API_KEY`), call
  plan-preview on a session and check `source` is `llm`. Without a key it returns `source: fallback`.

## Slice 2: debrief conversation
- **Goal:** the AI-led chat backend: persisted questions and messages, answer/skip/end, adaptive follow-ups,
  hard question cap, session-token auth for the embedded chat.
- **ADRs:** 0008, 0009.
- **Changed:** tables `debriefs`, `debrief_questions`, `debrief_messages` (migration 0002); `app/debrief.py`,
  `app/interpreter.py`, `app/prompts/interpreter_v1.md`; endpoints `POST /v1/sessions/{id}/debrief/start`,
  `GET /v1/sessions/{id}/debrief`, `POST /v1/sessions/{id}/debrief/answer`; `deps.get_debrief_repo`;
  per-call LLM timeout; background plan precompute at intake; `tests/test_debrief.py` (19 tests).
- **Verify:** `pytest -q` (56 tests, SQLite and Postgres); `python -m scripts.smoke` walks a full debrief using
  only the session token. With an LLM configured, check follow-ups and covered questions in the transcript.

## Slice 3: structured extraction and the confirm step (FR-4)
- **Goal:** turn a finished debrief into schema-valid, evidence-backed facts, let the agent confirm/edit/discard,
  and save them through the single write path.
- **ADRs:** 0010, 0011 (and an addendum to 0009).
- **Changed:** tables `extractions`, `extracted_facts` (migration 0003); `app/extraction.py`,
  `app/prompts/extractor_v1.md`; endpoints `POST/GET /v1/sessions/{id}/extraction` and
  `POST /v1/sessions/{id}/extraction/confirm`; `apply_facts` gained per-fact provenance and `commit=False`;
  auto-start on debrief completion; `tests/test_extraction.py` (21 tests).
- **Verify:** `pytest -q` (77 tests, SQLite and Postgres); `python -m scripts.smoke` runs debrief, extraction,
  confirm and profile read. With an LLM configured, check the proposals' evidence quotes and the `dropped` reasons.

## Slice 4: chat UI, mock admin panel, profile viewer (FR-7)
- **Goal:** the part a reviewer clicks through: an embeddable debrief chat with a review/confirm screen, a mock admin
  panel that launches it, and a tiny profile viewer.
- **ADRs:** 0012.
- **Changed:** `web/` (React + TypeScript + Vite; 36 component tests, optional live E2E test); `app/web.py` (serves the
  app, `frame-ancestors`); `GET /v1/whoami`; multi-stage `Dockerfile`; `FRAME_ANCESTORS` / `STATIC_DIR` settings;
  `tests/test_web.py`.
- **Verify:** `pytest -q` (83 tests); `cd web && npm ci && npm test && npm run build`;
  `LIVE_API=... LIVE_API_KEY=... npm run test:live` against a running server; open `/admin`, paste a key, press Debrief.

## Slice 5: voice answers (FR-3)
- **Goal:** record up to about 60 s instead of typing; server transcribes in a persisted background job; the agent edits
  the transcript before it becomes the answer.
- **ADRs:** 0013.
- **Changed:** table `voice_notes` (migration 0004); `app/voice.py`, `app/stt/` (interface, Gemini, dev stub),
  `app/lookup.py` (shared lookups); endpoints `POST /v1/sessions/{id}/voice`, `GET .../voice/{note_id}`,
  `POST .../voice/{note_id}/retry`; `voice_note_id` on answers; `voice_enabled` on the debrief state;
  `web/src/chat/VoiceInput.tsx`, recorder helpers and a fake microphone for tests; `tests/test_voice.py` (34 tests).
- **Verify:** `pytest -q` (117 tests, SQLite and Postgres); `cd web && npm test` (55 tests);
  start the server with `STT_PROVIDER=dev` and run `LIVE_VOICE=1 npm run test:live` or
  `SMOKE_VOICE_FILE=any.webm python -m scripts.smoke`. For real speech set `STT_PROVIDER=gemini`.

## Slice 6: submission documents
- **Goal:** the written deliverables a reviewer needs: a test script for the hosted app, the design note, and the two diagrams.
- **ADRs:** none (documentation only, no behaviour change).
- **Changed:** `REVIEWER_GUIDE.md`; `docs/design-note.md` and `.pdf` (built by `docs/build_design_note_pdf.py`);
  `docs/diagrams/` (`architecture` and `data-model`, SVG and PNG, rebuilt by `generate.py`); README (removed a stray shell
  heredoc from the end, added the guide to the layout); this file.
- **Verify:** open the README links (guide, design note, both diagrams); `python docs/diagrams/generate.py` and
  `python docs/build_design_note_pdf.py` rebuild the files; follow `REVIEWER_GUIDE.md` against the hosted app.

## Next
- Worker + jobs table (replace in-process background tasks), `profile.updated` webhook, dashboard, PII redaction toggle.
  (The profile viewer was built in slice 4.)
