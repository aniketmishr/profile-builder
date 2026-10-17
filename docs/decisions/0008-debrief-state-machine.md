# 0008 Debrief conversation: persisted state machine with hard limits
Status: accepted (slice 2)

**Context.** The AI leads a short chat with a human agent: at most 5 to 7 questions, skip/end-early, adapt to
answers (skip what is already covered, at most one follow-up for ambiguity), never invent facts, survive reloads,
closed tabs and double-clicks, and keep each turn fast (first question about 3 s, later turns about 5 s).

**Decision.**
- Three tables: `debriefs` (one per session: plan metadata, state, end reason), `debrief_questions` (status:
  pending, asked, answered, skipped, covered, dropped) and `debrief_messages` (the transcript; `meta` records the
  interpretation, prompt version and model behind each AI decision). Everything is persisted, so a reload resumes.
- Deterministic code owns flow control; the LLM only advises. Per answer, one small LLM call
  (`interpreter_v1`) returns clarity, an optional follow-up and which remaining questions are already covered.
  Code validates it: made-up question labels are ignored, a follow-up is only used when allowed.
- Limits live in code: total questions asked is at most `MAX_QUESTIONS` (follow-ups count), one follow-up per
  planned question, never a follow-up to a follow-up. Leftover questions become `dropped`.
- If the LLM is missing or fails, the default is "clear, nothing covered": the debrief still works, just not adaptively.
- Each answer names the question it answers (`question_id`). A stale id returns 409, so a double-submit cannot
  record two answers. Turns for one session are serialised by a row lock on the debrief.
- `POST .../debrief/start` is idempotent. The plan is also generated in the background at intake
  (`PRECOMPUTE_PLANS`) so the first question is ready when the chat opens. This is a best-effort in-process task:
  if it never runs, `start` creates the plan on demand.
- Interpretation uses a shorter timeout (`LLM_TURN_TIMEOUT_SECONDS`, default 4) than planning.

**Alternatives.** One free-form LLM conversation (cannot enforce the cap or test flow). Interpreting every answer
with extraction in the same call (couples two concerns; extraction happens once, after the debrief, in slice 3).
A job queue for the plan (needs the worker slice; the on-demand path already covers failure).

**Consequences.** After the last question the session is `debrief_complete`; slice 3 (extraction and confirm)
starts from there. Worst-case turn latency can exceed 5 s when the provider errors and retries; the fallback then applies.
The interpreter prompt has been tested only against scripted outputs, not a live model.
