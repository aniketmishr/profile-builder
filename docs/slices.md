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

## Next
- Slice 2: persisted debrief turns (answer handling, skip, end early, 5 to 7 cap, adaptive follow-ups).
