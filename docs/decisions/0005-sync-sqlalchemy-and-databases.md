# 0005 Sync SQLAlchemy; Postgres is the target, SQLite for dev/tests
Status: accepted (slice 0)

**Context.** The brief expects Postgres when hosted, allows SQLite locally, and the scale target is modest
(50 profile reads/s, 200 concurrent debriefs).

**Decision.** SQLAlchemy 2.0 with synchronous sessions (FastAPI runs sync endpoints in a thread pool).
Postgres (Neon) is the supported production database. SQLite exists so `pytest` and a fresh clone work with
zero setup. The suite also runs against Postgres via `TEST_DATABASE_URL`, and both must pass. Code stays
portable by using generic types, savepoints instead of dialect-specific upserts, and a `JSON`/`JSONB` variant.

**Alternatives.** Async SQLAlchemy (more moving parts, no need at this scale). Postgres only (tests need Docker).

**Consequences.** Avoid Postgres-only SQL in app code. Migrations are authored by hand and checked with
`alembic check` for drift against the models.
