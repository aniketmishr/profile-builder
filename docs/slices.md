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

## Next
- Chat UI + mock admin panel (embeddable, uses the session token), including the review/confirm screen.
- Voice: audio upload, transcription job with polling, editable transcript.
- Worker + jobs table (replace in-process background tasks), `profile.updated` webhook, profile viewer, polish.
