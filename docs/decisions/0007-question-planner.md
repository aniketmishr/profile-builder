# 0007 Question planner: fallback, caps in code, untrusted input
Status: accepted (slice 1)

**Context.** The debrief must be short (5 to 7 questions), task-aware, friendly, never invent facts, and the
first question must appear quickly even if the LLM is slow or down.

**Decision.** `planner.plan_questions()` returns a plan plus metadata (`source`, `prompt_version`, `model`,
`latency_ms`, `error`).
- Prompts are files (`app/prompts/planner_v1.md`); the file name is the version recorded with results.
- The LLM returns questions with a category and a one-line rationale; ids are assigned by code. Count is capped
  (`MAX_QUESTIONS`, default 7) and duplicates dropped in code, not only in the prompt.
- If there is no provider, it fails, or output stays invalid after one repair, a deterministic
  task-aware fallback plan is returned, so the debrief can always start.
- The transcript excerpt is untrusted: wrapped in a tag, truncated, closing tags neutralised, and the prompt tells
  the model to treat it as data. Questions may only refer to what the excerpt literally says.
- Known profile facts are passed in so the model does not re-ask what is already known.
- The intro line is built in code (no LLM variance).

**Alternatives.** Fully scripted questions (not context-aware). One free-form conversation with no plan
(harder to cap and test). Planning every turn (latency on each answer).

**Consequences.** Slice 2 should generate and persist the plan when the session opens (not on the first turn)
to meet the 3-second first-question target. `POST /v1/sessions/{id}/plan-preview` (dev only) lets you inspect
a plan and its provenance. Prompt changes mean a new file (`planner_v2.md`) and a constant bump.
