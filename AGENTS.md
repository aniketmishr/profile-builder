# AGENTS.md: read this first

Service: stores per-user profile facts captured after support tasks. FastAPI + SQLAlchemy 2 (sync) + Postgres.
Reasoning for every major choice is in `docs/decisions/` (ADRs). Progress is in `docs/slices.md`.

## Rules that must hold
1. **Isolation:** only `app/repo.py` queries tenant data, through `ScopedRepo` (no tenant argument on its
   methods). Handlers never touch the DB session. New endpoint means a new isolation test. (ADR 0001)
2. **Facts:** only `services.apply_facts()` writes facts. Never insert `ProfileFact` rows elsewhere. Facts are
   append-only; one current row per key. (ADR 0003, 0004)
3. **Read path has no LLM.** Profile JSON, history and context are built from the database only.
4. **LLM access** goes through `app/llm` (`generate_structured`). Never call a provider SDK or HTTP API from
   services or routes. Always validate output with a Pydantic schema. Provide a fallback for failures. (ADR 0006)
5. **Prompts are versioned files** in `app/prompts/`. Change a prompt by adding a new version file and bumping
   the constant that references it. Record the version with results.
6. **Customer text is untrusted** (transcripts, agent answers). Wrap it in tags, treat it as data in prompts.
7. **Never invent facts.** Unknown stays unknown. Each saved fact needs an evidence quote from the agent's words.
8. **Secrets** only in environment variables. API keys are stored hashed. Never log keys or full transcripts.
9. **Portability:** no Postgres-only SQL in app code (SQLite is used for fast tests). Migrations are hand-written
   Alembic files; run `alembic check` to detect drift from the models. (ADR 0005)

10. **Debrief flow control is code, not prompts:** question cap, follow-up limits, skip/end and stale-answer
    checks live in `app/debrief.py`. The LLM only advises (`interpreter`) and every output is validated. (ADR 0008)
11. **Chat endpoints** must use `deps.get_debrief_repo` (API key or session token bound to one session). Do not
    hand a session token access to profile or tenant-wide endpoints. (ADR 0009)
12. **Nothing the model says reaches the profile unchecked.** Extracted facts need an evidence quote verified against
    the agent's answers (`extraction.sanitize`) and the agent's confirmation; saving goes through `apply_facts` in one
    transaction with the extraction status. Never write LLM output straight into `profile_facts`. (ADR 0010, 0011)
13. **The chat holds only the session token.** Never put the tenant API key, or code that needs it, in the chat
    code path. Keep `web/src/types.ts` in sync with `app/schemas.py`. The chat page must stay embeddable
    (`frame-ancestors` from config) and must not log or cache the token. (ADR 0012)
14. **Voice audio is private and short-lived.** Never add an endpoint that serves audio, never log audio or transcript
    text, and keep the content sniffing and size caps. A transcript is only a draft until the agent sends it as the
    answer. Speech-to-text goes through `app/stt` like the LLM goes through `app/llm`. (ADR 0013)

## Workflow for a change
1. Write or update the ADR first (what, why, alternatives, consequences). Add it to `docs/decisions/README.md`.
2. Implement with tests. Run `pytest -q` (and with `TEST_DATABASE_URL` for Postgres when touching queries or migrations).
3. Update `docs/slices.md` and the README status table.

## Map
`app/api.py` routes (thin) → `app/services.py` / `app/planner.py` (rules) → `app/repo.py` (queries) → models.
`app/debrief.py` conversation state machine, `app/interpreter.py` per-answer interpretation, `app/extraction.py` extraction + confirm, `app/voice.py` + `app/stt/` voice notes and speech-to-text providers, `app/llm/` providers, `app/prompts/` prompt files, `app/web.py` serves the built React app from `web/` (chat, mock admin panel, profile viewer), `scripts/` seed and smoke,
`tests/` backend tests, `web/src/**/*.test.tsx` frontend tests.
