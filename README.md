# Profile Builder

An AI-powered user profiling system for a support operation. When a human agent finishes a task, the system runs a short
AI-led debrief with the agent (typed or spoken), extracts structured, evidence-backed facts about the customer, lets the
agent confirm or edit them, and stores them in a growing per-user profile that other AI systems read through an API.

Built as a 3-day take-home with FastAPI, PostgreSQL and React.

**Start here:** [Reviewer guide](REVIEWER_GUIDE.md) (test the hosted app in 10 minutes) ·
[Design note](docs/design-note.pdf) · [Architecture diagram](docs/diagrams/architecture.png) ·
[Data model](docs/diagrams/data-model.png) · [Decision records](docs/decisions/README.md) · API docs at `/docs` on the running app.

## How it works

1. A task closes. The admin panel's server calls `POST /v1/sessions` with the tenant API key and the task context. The call
   is idempotent and returns a session id and a `chat_url` carrying a signed token.
2. The admin panel embeds `chat_url` in an iframe. The AI leads a short debrief: 3 to 7 questions tailored to the task,
   answered by typing or by a voice note that is transcribed and can be edited.
3. The AI adapts: it skips questions an earlier answer already covered and asks at most one follow-up for an unclear answer.
4. When the debrief ends, the AI proposes facts. Each fact must quote the agent's own words, which code verifies.
5. The agent keeps, edits or discards each fact and confirms. The facts are saved in one transaction.
6. Facts are append-only: a new value supersedes the old one and the old one stays in history. Other AI systems read the
   merged profile, the history, or an LLM-ready context block. No LLM runs on the read path.

## Architecture

![Architecture and request flow](docs/diagrams/architecture.png)

![Data model](docs/diagrams/data-model.png)

One FastAPI service (API, background tasks, and the built React app) plus PostgreSQL. LLM and speech-to-text providers sit
behind small interfaces (Gemini is implemented). Tenant isolation is enforced in one repository layer and backed by
composite foreign keys. The reasoning behind each choice is in the [design note](docs/design-note.pdf) and the
[decision records](docs/decisions/README.md).

## Requirements status

| Requirement | Status | Notes |
|---|---|---|
| FR-1 Session intake | Done | `POST /v1/sessions`, scoped by tenant, agent and end user, idempotent on `(tenant_id, idempotency_key)`, returns a session id and chat URL |
| FR-2 AI-guided debrief chat | Done | Task-aware plan, at most 7 questions (enforced in code), skip, end early, skips covered questions, one follow-up for ambiguity |
| FR-3 Voice with transcription | Done | Record up to 60 s, background transcription job with polling, editable transcript, audio private and deleted after use |
| FR-4 Structured extraction | Done | Pydantic schema, 7 categories, confidence, evidence quote verified in code, confirm / edit / discard before saving |
| FR-5 Per-user profile store | Done | Append-only history, documented conflict rule, isolation tests across every endpoint |
| FR-6 Retrieval API | Done | `GET /v1/profiles/{id}`, `/context` (with `max_tokens`), `/history`; API keys hashed at rest; OpenAPI at `/docs` |
| FR-7 Admin panel integration | Partial | Embeddable chat, mock admin panel and profile viewer done. **The `profile.updated` webhook was not built** |
| FR-8 Operational basics | Partial | Structured JSON logs with tenant and session ids, `/health`, graceful provider failure with fallbacks, seed script done. **Dashboard and PII redaction toggle not built** |

Also not built: a separate worker with a jobs table (background work runs in-process with its state saved in the database)
and the optional demo video. See [Limitations](#limitations-and-what-was-cut).

## Quick start

### Hosted

Follow the [reviewer guide](REVIEWER_GUIDE.md). It needs the app URL and demo keys from the submission email.

### Local with Docker

```bash
docker compose up --build                              # app + API on http://localhost:8000
docker compose run --rm api python -m scripts.seed     # prints one API key per demo tenant (shown once)
```

Open http://localhost:8000/admin, paste the `tn_acme` key and press **Debrief** on a task. Swagger is at http://localhost:8000/docs.
The compose file turns on the dev endpoints and uses fallback questions; see [Configuration](#configuration) to enable the LLM and voice.

### Local without Docker

Needs Python 3.11 or newer (developed on 3.12) and Node 20 or newer (developed on 22).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # point DATABASE_URL at a Postgres, or delete that line to use SQLite (dev.db)
alembic upgrade head
python -m scripts.seed          # prints one API key per demo tenant (shown once)
(cd web && npm ci && npm run build:api)    # builds the UI into app/static
uvicorn app.main:app --reload   # http://localhost:8000/admin
```

### Check the whole flow from the command line

```bash
API_KEY=pk_... BASE_URL=http://localhost:8000 python -m scripts.smoke
```

It creates a session, runs a debrief with the session token, waits for extraction, confirms, and reads the profile back.
It needs `ENABLE_DEBUG_ENDPOINTS=true`. Add `SMOKE_VOICE_FILE=answer.webm` to include a voice answer when voice is enabled.

## Tests

```bash
pytest -q                                   # backend: 117 tests on SQLite, no setup needed
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/profiles_test pytest -q   # same suite on an empty Postgres
cd web && npm ci && npm test                # frontend: 55 component tests with a mocked API
cd web && npm run typecheck                 # TypeScript
# optional end-to-end: the real chat component against a running server (no mocks)
LIVE_API=http://localhost:8000 LIVE_API_KEY=pk_... npm run test:live
```

What the tests cover: tenant isolation through every endpoint, idempotent intake (including the insert race), supersede and
history, the question cap and follow-up limits, stale and double-submitted answers, evidence verification, atomic confirm,
voice upload validation and job recovery, session-token scope, and the chat flows (edit, discard, retry, resume).
Both databases must pass. For the voice end-to-end test start the server with `STT_PROVIDER=dev` and set `LIVE_VOICE=1`.

## Configuration

Everything is an environment variable (see `.env.example`). No secrets are stored in the repo.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite `dev.db` | Postgres URL (`postgres://` and `postgresql://` both work) |
| `SESSION_TOKEN_SECRET` | dev value | Signs chat session tokens. **Set a long random value** |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Base of the `chat_url` returned to the admin panel |
| `FRAME_ANCESTORS` | `*` | Origins allowed to embed the chat in an iframe. Use your panel's origin, or `'self'` for the mock panel only |
| `ENABLE_DEBUG_ENDPOINTS` | `false` | Turns on hand-written facts and plan preview (needed by `scripts.smoke`) |
| `LLM_PROVIDER` | `none` | `none` uses built-in fallback questions and notes; `gemini` enables the AI |
| `LLM_MODEL` | empty | Required with a provider. Copy the current model id from Google AI Studio |
| `GEMINI_API_KEY` | empty | Key from Google AI Studio |
| `STT_PROVIDER` | `none` | `none` (voice off), `gemini` (real transcription), `dev` (fixed stub transcript for trying the flow) |
| `STT_MODEL` | empty | Falls back to `LLM_MODEL` |
| `MAX_QUESTIONS` | `7` | Hard cap on questions per debrief, follow-ups included |
| `LLM_TIMEOUT_SECONDS` / `LLM_TURN_TIMEOUT_SECONDS` | `8` / `4` | Planning timeout / per-answer timeout |
| `EXTRACTION_TIMEOUT_SECONDS` / `MAX_EXTRACTED_FACTS` | `20` / `20` | Extraction call timeout / cap on proposed facts |
| `AUTO_EXTRACT` / `PRECOMPUTE_PLANS` | `true` / `true` | Start extraction when a debrief ends / plan questions in the background at intake |
| `EXTRACTION_STALE_SECONDS` / `VOICE_STALE_SECONDS` | `120` / `90` | A job left running this long is treated as dead and can be re-run |
| `STT_TIMEOUT_SECONDS` / `MAX_AUDIO_BYTES` / `MAX_AUDIO_SECONDS` | `30` / `2000000` / `75` | Voice limits |
| `KEEP_AUDIO` / `MAX_VOICE_NOTES_PER_SESSION` | `false` / `20` | Audio is deleted after transcription unless set; per-session cap |
| `SESSION_TOKEN_TTL_SECONDS` | `86400` | Lifetime of a chat token |
| `STATIC_DIR` / `LOG_LEVEL` | `app/static` / `INFO` | Location of the built UI / log level |

**To enable the AI features:** set `LLM_PROVIDER=gemini`, `LLM_MODEL=<model id>` and `GEMINI_API_KEY`; add `STT_PROVIDER=gemini`
for voice. Without them everything still works: questions come from built-in task-aware templates, answers are treated as clear,
and the agent's own words are offered as notes to save. Voice is hidden unless `STT_PROVIDER` is set. Recording needs HTTPS
(or localhost), and inside an iframe the host page must allow it with `<iframe allow="microphone">`.

## Deploying (Neon + Render)

1. **Database:** create a project at neon.tech and copy the connection string (keep `?sslmode=require`).
2. **Code:** push this repository to GitHub.
3. **Render:** New > Blueprint (reads `render.yaml`) or New > Web Service > Docker. Set `DATABASE_URL` to the Neon string.
   The image builds the UI in a Node stage and runs migrations on every start. `SESSION_TOKEN_SECRET` is generated.
4. After the first deploy set `PUBLIC_BASE_URL` to the Render URL and redeploy. Optionally set `FRAME_ANCESTORS` to `'self'`
   and add the `LLM_*`, `GEMINI_API_KEY` and `STT_*` variables.
5. **Seed from your machine** (the free plan has no shell), pointing at Neon:
   ```bash
   pip install -r requirements.txt
   DATABASE_URL='<neon url>' python -m scripts.seed      # prints the demo keys once; --new-keys mints more
   ```
6. **Verify:** `BASE_URL=https://<app>.onrender.com API_KEY=<tn_acme key> python -m scripts.smoke`, then open `/admin`.

As far as I know, free web services on Render sleep when idle, so the first request after a pause can take up to a minute.
Check the current free-tier behaviour, or use a cheap always-on plan during review. The same Dockerfile works on Fly.io or Railway.
`render.yaml` sets `ENABLE_DEBUG_ENDPOINTS=true` for demos; turn it off for anything real.

## API at a glance

All endpoints are in the OpenAPI page at `/docs`. "Key" means the `X-API-Key` header; "Key or token" also accepts the
`X-Session-Token` header from a session's `chat_url`, which only works for that one session.

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /v1/sessions` | Key | Create a debrief session (idempotent): 201 new, 200 repeat, 409 key reused for another task, 403 tenant mismatch |
| `GET /v1/sessions/{id}` | Key | Session status and a fresh `chat_url` |
| `POST /v1/sessions/{id}/debrief/start` | Key or token | Open the debrief: intro and first question (idempotent) |
| `GET /v1/sessions/{id}/debrief` | Key or token | Conversation state: messages, question statuses, progress |
| `POST /v1/sessions/{id}/debrief/answer` | Key or token | Answer, skip or end; optional `voice_note_id` |
| `POST /v1/sessions/{id}/voice?question_id=` | Key or token | Upload a recording (raw audio body); returns a job to poll |
| `GET /v1/sessions/{id}/voice/{note_id}` | Key or token | Poll the transcription job; the transcript is a draft to edit |
| `POST /v1/sessions/{id}/voice/{note_id}/retry` | Key or token | Retry a failed transcription |
| `GET /v1/sessions/{id}/extraction` | Key or token | Proposed facts with evidence quotes |
| `POST /v1/sessions/{id}/extraction` | Key or token | Re-run extraction (until confirmed) |
| `POST /v1/sessions/{id}/extraction/confirm` | Key or token | Keep, edit or discard facts and save them |
| `GET /v1/profiles/{end_user_id}` | Key | Merged profile: current facts and metadata |
| `GET /v1/profiles/{end_user_id}/history` | Key | Every version of every fact, with source sessions |
| `GET /v1/profiles/{end_user_id}/context?max_tokens=` | Key | LLM-ready text block within a token budget; `format=text` for plain text |
| `GET /v1/whoami` | Key | Tenant of the key |
| `GET /health` | None | Process and database check |
| `POST /v1/profiles/{id}/facts`, `POST /v1/sessions/{id}/plan-preview` | Key, dev only | Hand-written facts and plan preview (`ENABLE_DEBUG_ENDPOINTS`) |

```bash
# create a session (repeat the call and you get 200 with the same session_id)
curl -X POST $BASE/v1/sessions -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "idempotency_key":"task_8f3a21","tenant_id":"tn_acme",
  "agent":{"id":"ag_104","name":"Priya S."},"end_user":{"id":"eu_55021","display_name":"Rahul M."},
  "task":{"id":"task_8f3a21","type":"refund_dispute","title":"Refund for damaged order #44871","channel":"whatsapp"},
  "locale":"en-IN"}'

curl -H "X-API-Key: $KEY" $BASE/v1/profiles/eu_55021                          # merged profile
curl -H "X-API-Key: $KEY" "$BASE/v1/profiles/eu_55021/context?max_tokens=150"  # e.g. "Rahul M. (eu_55021): Contact: preferred channel whatsapp; ..."
```

## Repository layout

```
app/          FastAPI service
              api.py (routes) · debrief.py, planner.py, interpreter.py, extraction.py, voice.py, services.py (rules)
              repo.py (the only code that queries tenant data) · models.py · llm/ · stt/ · prompts/ (versioned) · web.py
web/          React + TypeScript app: embeddable chat, mock admin panel, profile viewer (with tests)
migrations/   Alembic, 0001 to 0004
scripts/      seed.py (demo tenants and keys), smoke.py (end-to-end check)
tests/        backend tests: isolation, idempotency, debrief, extraction, voice, web
docs/         design-note.pdf/.md · diagrams/ · decisions/ (13 records) · slices.md (what changed in each step)
AGENTS.md     rules for contributors and coding agents
Dockerfile · docker-compose.yml · render.yaml · .env.example
```

## Documentation map

| Document | What it answers |
|---|---|
| [docs/design-note.pdf](docs/design-note.pdf) | Key decisions, scaling analysis, limitations, what comes next |
| [docs/diagrams/](docs/diagrams/) | Architecture and request flow, data model (SVG and PNG; `generate.py` rebuilds them) |
| [docs/decisions/](docs/decisions/README.md) | One short record per major decision: context, choice, alternatives, consequences |
| [docs/slices.md](docs/slices.md) | The build history in six steps and how to verify each |
| [AGENTS.md](AGENTS.md) | The rules the code relies on (isolation, single write path, no LLM on reads) |

## Limitations and what was cut

- **Not built:** a separate worker with a jobs table, the `profile.updated` webhook, the dashboard, the PII redaction toggle,
  and the demo video.
- **Providers were not exercised for real here.** LLM and speech behaviour was tested with scripted outputs, HTTP mocks and a
  stub, so real prompt quality (follow-ups, covered-question detection, extraction accuracy, mixed Hindi and English speech) is
  unmeasured. There is no evaluation set yet.
- **The UI has not been seen in a real browser.** It was tested with component tests and an end-to-end run in a simulated
  browser. The microphone path is untested on real devices.
- **The Docker image build was not run in the development sandbox;** its steps (`npm ci`, build, migrations, tests) were run individually.
- Background jobs are in-process, so a restart can leave a job to be re-run on the next poll. There is no rate limiting,
  key rotation endpoint, session-token revocation or transcript retention policy. Multi-valued fact keys overwrite unless the
  value is a list. The chat can be framed by any site until `FRAME_ANCESTORS` is set.
- The evidence check proves a quote exists, not that the value is the right reading of it. The agent's review is the backstop.
EOF
cat > REVIEWER_GUIDE.md <<'EOF'
# Reviewer guide: test the hosted app

About 10 minutes. You need three things from the submission email:

- `<APP_URL>`, the app address
- `<ACME_KEY>`, the API key for tenant `tn_acme`
- `<GLOBEX_KEY>`, the API key for tenant `tn_globex` (only used for the isolation check)

If the app has been idle, the first request can take up to a minute to wake up.

## 1. Check it is up (30 seconds)

1. Open `<APP_URL>/health`. Expect `{"status":"ok","db":"ok"}`.
2. Open `<APP_URL>/docs` (Swagger). Click **Authorize** and paste `<ACME_KEY>`.

## 2. Run the full loop on a refund task (3 minutes)

1. Open `<APP_URL>/admin`, paste `<ACME_KEY>` and press **Connect**. You see "Tenant tn_acme" and four closed tasks.
2. Press **Debrief** on "Refund for damaged order #44871". The chat opens on the right with an intro
   ("Quick debrief on Rahul M. ...") and one question at a time ("Question 1 of up to 7").
3. Answer the questions in turn (type and press Enter):
   - `he said never email him, only whatsapp, and not after 9pm`
   - press **Skip** on the next one
   - `his wife places most orders, he just handles complaints`
   - `he asked for store credit instead of refund next time`
4. After the last answer you see "Preparing your summary…", then **Here's what I'll save**. Each fact shows a confidence badge
   and **You said: "..."**, a quote from your own words.
5. Edit one value, press **Discard** on another fact, then press **Save**. Expect **Saved ✓** in the chat and a
   "Profile updated" message in the panel.

If the AI is enabled, the questions are tailored to refunds and adapt to your answers. If it is not enabled you will see
built-in question templates and your own words offered as notes. Both are expected behaviour.

## 3. Look at the profile (1 minute)

Press **Profile** on that task (or open the **Profile viewer** tab). Expect the current facts with confidence, the evidence
quote and the source session, an "edited by agent" tag on the fact you edited, no trace of the one you discarded, and the
LLM-ready context block at the bottom.

## 4. Check idempotency and resume (30 seconds)

Go back to **Closed tasks** and press **Debrief** on the same refund task again. Expect "Resumed existing session" and the
finished conversation with **Saved ✓**, not a duplicate. Tick "Start a fresh session each time" to run it again from the start.

## 5. Try a different task type (2 minutes)

Press **Debrief** on "Set up a new business account" (Meera T.). The questions differ from the refund ones, leaning toward
products, communication style and constraints. Answer, review, save, then open her profile.

## 6. Contradict an old fact and read the history (1 minute)

Press **Debrief** on "Move delivery slot for order #45102" (Rahul again) and answer that he now prefers SMS in the morning, for
example `he now wants SMS, mornings only, no whatsapp`. Save. In the Profile viewer for `eu_55021`, open **History** for the
changed fact: the old value is marked **superseded** with its original session, and the new one is **current**.

## 7. Voice (optional, 1 minute)

If the chat shows a **🎤 Record** button, voice is enabled. Press it, allow the microphone, speak for a few seconds and press
**Stop**. The transcript appears in the text box: edit it, then send. No button means voice is off on this deployment.

## 8. Check the API directly (2 minutes)

```bash
APP=<APP_URL>; KEY=<ACME_KEY>; G=<GLOBEX_KEY>

# merged profile, history and LLM-ready context (no LLM call on these reads)
curl -s -H "X-API-Key: $KEY" $APP/v1/profiles/eu_55021
curl -s -H "X-API-Key: $KEY" $APP/v1/profiles/eu_55021/history
curl -s -H "X-API-Key: $KEY" "$APP/v1/profiles/eu_55021/context?max_tokens=150"

# idempotent intake: prints 201, then 200 for the identical repeat
BODY='{"idempotency_key":"review-1","tenant_id":"tn_acme","agent":{"id":"ag_104","name":"Priya S."},"end_user":{"id":"eu_55021","display_name":"Rahul M."},"task":{"id":"review-1","type":"refund_dispute","title":"Review test"}}'
for i in 1 2; do curl -s -o /dev/null -w "%{http_code}\n" -X POST $APP/v1/sessions -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$BODY"; done

# isolation between tenants
curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: $G" $APP/v1/profiles/eu_55022   # 404: Meera exists only in tn_acme
curl -s -H "X-API-Key: $G" $APP/v1/profiles/eu_55021                                      # same id in tn_globex: a separate profile, no Acme facts
curl -s -o /dev/null -w "%{http_code}\n" -X POST $APP/v1/sessions -H "X-API-Key: $G" -H "Content-Type: application/json" -d "$BODY"   # 403: body says tn_acme
curl -s -o /dev/null -w "%{http_code}\n" $APP/v1/profiles/eu_55021                       # 401: no key
```

## What good looks like

| Check | Expected |
|---|---|
| Health and docs | `ok` and a Swagger page |
| Refund debrief | One question at a time, at most 7, skip and end work, no invented facts |
| Review screen | Every fact has an evidence quote from your words; edit and discard work |
| Saved profile | Facts appear in the viewer with confidence, evidence and source; edits are tagged |
| Repeat Debrief | Resumes the same session |
| Different task type | Different questions |
| Contradiction | Old value kept as history, new value current |
| API | 201 then 200 for repeats; other tenant gets 404 or an empty separate profile; wrong tenant in the body gets 403; no key gets 401 |
