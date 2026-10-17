# Profile Builder: Day 1 foundation

FastAPI + Postgres service that stores per-user profile facts captured after support tasks.
This is the Day 1 spine: **data model, session intake, profile store, retrieval API, deployable.**
The AI debrief chat, extraction and voice come on top of this on Days 2 and 3.

## What is built

| Requirement | Status |
|---|---|
| FR-1 `POST /v1/sessions`, idempotent on `(tenant_id, idempotency_key)`, returns `session_id` + signed `chat_url` | done |
| FR-5 append-only fact store, supersede with history, merged "current" view | done |
| FR-5 isolation enforced in one place + automated cross-tenant tests | done |
| FR-6 `GET /v1/profiles/{id}`, `/history`, `/context?max_tokens=` (no LLM on read path), API keys, Swagger at `/docs` | done |
| FR-8 JSON logs with tenant/session ids, `/health` with DB check, seed script | done |
| Hand-write facts (dev only): `POST /v1/profiles/{id}/facts` | done, gated by `ENABLE_DEBUG_ENDPOINTS` |
| LLM interface (Gemini provider) + task-aware question planner with deterministic fallback | done (slice 1) |
| Dev preview `POST /v1/sessions/{id}/plan-preview` | done, gated by `ENABLE_DEBUG_ENDPOINTS` |
| FR-2 debrief conversation API: persisted turns, skip/end, adaptive follow-ups, 7-question cap, session-token auth | done (slice 2) |
| FR-4 extraction + confirm step, chat UI, mock admin panel, FR-3 voice | not yet (next slices) |
| `/chat/{session_id}` page that `chat_url` points to | not yet (Day 2), the URL is generated and its token is verifiable |

## Layout

```
app/
  main.py       app, /health, access log
  api.py        routes (thin: parse, call service, return)
  services.py   business rules: idempotent intake, apply_facts (conflict rule), context builder
  repo.py       ONLY place that queries tenant data; ScopedRepo is locked to one tenant
  deps.py       X-API-Key -> tenant -> ScopedRepo
  planner.py    debrief question planning (LLM + fallback)
  debrief.py    conversation state machine (turns, limits)   interpreter.py  per-answer interpretation
  llm/          provider interface, validate-and-repair, Gemini provider
  prompts/      versioned prompt files (planner_v1.md)
  models.py  schemas.py  security.py  config.py  db.py  logging.py  ids.py
migrations/     Alembic (0001_init)
docs/           decisions/ (ADRs), slices.md. Agents: read AGENTS.md first
scripts/        seed.py, smoke.py
tests/          sessions, profiles, isolation
```

## Run locally

### Option A: Docker (one command)

```bash
docker compose up --build            # API on http://localhost:8000, Swagger at /docs
docker compose run --rm api python -m scripts.seed    # prints one API key per demo tenant
```

### Option B: without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # point DATABASE_URL at any Postgres (or delete the line to use SQLite)
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

### Try it

```bash
export API_KEY=pk_...                # from the seed output (tn_acme)
BASE_URL=http://localhost:8000 python -m scripts.smoke    # runs the whole Day 1 flow
```

## Tests

```bash
pytest -q                                              # SQLite, no setup needed
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/profiles_test pytest -q   # empty Postgres DB
```
They cover idempotency (including the insert-race path), supersede + history, validation, the context
budget, and tenant isolation through every endpoint. Both backends pass.

## Environment variables

| Name | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (`postgres://` and `postgresql://` are both accepted). Falls back to SQLite for dev |
| `SESSION_TOKEN_SECRET` | signs the chat-session token. Use a long random value |
| `PUBLIC_BASE_URL` | base for `chat_url`, e.g. your hosted URL |
| `ENABLE_DEBUG_ENDPOINTS` | `true` exposes the hand-write facts endpoint |
| `LOG_LEVEL` | default `INFO` |
| `LLM_PROVIDER` | `none` (default, fallback questions only) or `gemini` |
| `LLM_MODEL` | required with a provider: copy the current model id from Google AI Studio |
| `GEMINI_API_KEY` | key from Google AI Studio |
| `LLM_TIMEOUT_SECONDS` / `LLM_TURN_TIMEOUT_SECONDS` / `MAX_QUESTIONS` | default `8` / `4` / `7` |
| `PRECOMPUTE_PLANS` | default `true`: build the question plan in the background at intake |

No secrets live in the repo. API keys are stored only as SHA-256 hashes.

## Host it (Neon + Render, about 15 minutes)

1. **Database:** create a project at neon.tech, copy the connection string (keep `?sslmode=require`).
2. **Code:** push this folder to a private GitHub repo.
3. **Render:** New > Blueprint (reads `render.yaml`), or New > Web Service > Docker. Set
   `DATABASE_URL` to the Neon string. Leave `PUBLIC_BASE_URL` empty for the first deploy.
   `SESSION_TOKEN_SECRET` is generated for you.
4. After the first deploy, set `PUBLIC_BASE_URL` to the Render URL (e.g. `https://profile-builder.onrender.com`)
   and redeploy. Migrations run automatically on every start.
5. **Seed from your laptop** (Render's free plan has no shell), pointing at Neon:
   ```bash
   pip install -r requirements.txt
   DATABASE_URL='<neon url>' python -m scripts.seed
   ```
   Save the printed keys. They cannot be shown again (`--new-keys` mints more).
6. **Verify the hosted app:**
   ```bash
   BASE_URL=https://<your-app>.onrender.com API_KEY=<tn_acme key> python -m scripts.smoke
   ```
   Open `https://<your-app>.onrender.com/docs` for Swagger.

Notes: free web services on Render sleep when idle, so the first request after a pause can take
a while. Check current free-tier behaviour, and consider a cheap always-on plan for review week.
The same Dockerfile works on Fly.io or Railway (it honours `$PORT`).

## API (all need `X-API-Key`)

```bash
# create a session (idempotent: repeat the call and you get 200 + the same session_id)
curl -X POST $BASE/v1/sessions -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{
  "idempotency_key":"task_8f3a21","tenant_id":"tn_acme",
  "agent":{"id":"ag_104","name":"Priya S."},"end_user":{"id":"eu_55021","display_name":"Rahul M."},
  "task":{"id":"task_8f3a21","type":"refund_dispute","title":"Refund for damaged order #44871","channel":"whatsapp"},
  "locale":"en-IN"}'

# write facts by hand (dev only), using the session_id from above
curl -X POST $BASE/v1/profiles/eu_55021/facts -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{
  "source_session_id":"ss_...","facts":[{"category":"contact_preferences","key":"preferred_channel",
  "value":"whatsapp","confidence":0.95,"evidence":"only whatsapp"}]}'

curl $BASE/v1/profiles/eu_55021                       -H "X-API-Key: $API_KEY"   # merged current facts
curl $BASE/v1/profiles/eu_55021/history               -H "X-API-Key: $API_KEY"   # every version + sessions
curl "$BASE/v1/profiles/eu_55021/context?max_tokens=150" -H "X-API-Key: $API_KEY" # LLM-ready text
```

Status codes: `201` new session, `200` duplicate call, `401` bad key, `403` body tenant differs from key,
`404` unknown or other-tenant resource, `409` idempotency key reused for a different task, `422` invalid body.

## Design decisions (short)

- **Isolation in one place.** `repo.ScopedRepo` is built from the tenant behind the API key; its methods take no
  tenant argument. The schema backs it up with composite keys: `agents` and `end_users` are keyed by
  `(tenant_id, id)`, and a fact's end user and source session must exist in the same tenant.
  Cross-tenant lookups return 404, not 403, so existence never leaks.
- **Idempotency.** Unique `(tenant_id, idempotency_key)`. The insert runs in a savepoint; if a concurrent call wins,
  the loser loads the winner's row. Same key with a different task or user gives 409.
- **Conflict rule v1.** Latest write for a `(category, key)` supersedes the old row, which stays in history with its
  source session. Same value again is a no-op. Duplicate keys inside one batch keep the highest confidence.
  A partial unique index (`WHERE is_current`) guarantees one current value per key. Writers are serialised per
  profile with a row lock.
- **One write path.** `services.apply_facts` is what the Day 2 extractor will call, so hand-written and
  LLM-written facts follow the same rule. `provenance` (JSON) is where the prompt version and tool call will go.
- **Read path has no LLM.** The context block is built deterministically; lowest-priority categories are dropped
  first to fit `max_tokens` (about 4 characters per token).
- **Sync SQLAlchemy.** Simpler to test and plenty for the stated read rate; noted for the design note.

## Known limitations (honest list)

- Multi-valued keys (e.g. several avoided channels) overwrite each other unless the value is a list.
- Token counting is a character estimate, not a real tokenizer.
- No rate limiting, key rotation endpoint or webhook yet. Keys are created with `scripts/seed.py`.
- `chat_url` points to a page that does not exist until Day 2.

## The debrief conversation

```bash
# session_id and the token inside chat_url come from POST /v1/sessions
curl -X POST $BASE/v1/sessions/$SID/debrief/start -H "X-Session-Token: $TOKEN"        # intro + first question
curl -X POST $BASE/v1/sessions/$SID/debrief/answer -H "X-Session-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"question_id":"<current_question_id from the last response>","action":"answer","text":"only whatsapp, not after 9pm"}'
#   action: "answer" | "skip" | "end"     (typing "skip" also skips)
curl $BASE/v1/sessions/$SID/debrief -H "X-Session-Token: $TOKEN"                      # state, messages, progress
```
Debrief endpoints accept `X-Session-Token` (embedded chat) or `X-API-Key` (admin panel). Each response is the full
state (`state`: not_started | active | complete, `current_question_id`, `progress`, `questions`, `messages`).
`409` means the debrief is complete or not started, or `question_id` is stale (a double-submit).
Without an LLM it runs on the fallback questions with no adaptivity; with one, answers can trigger a
follow-up or skip questions the agent already covered.

## Try the question planner

```bash
# 1. create a session (see API section), note its session_id
# 2. preview the plan: without an LLM key this returns source "fallback"
curl -X POST $BASE/v1/sessions/ss_.../plan-preview -H "X-API-Key: $API_KEY"
# 3. with LLM_PROVIDER=gemini, LLM_MODEL=<id>, GEMINI_API_KEY=<key> set, source becomes "llm"
```

## Docs

`AGENTS.md` (rules for contributors and coding agents), `docs/decisions/` (why each major choice was made),
`docs/slices.md` (what each slice changed and how to verify it).
