# Decision records (ADRs)

One short note per significant decision, written in the same change that introduces it.
Format: Context, Decision, Alternatives considered, Consequences. Never rewrite history: if a decision
changes, add a new ADR and mark the old one `Superseded by NNNN`.

| # | Decision | Slice |
|---|---|---|
| [0001](0001-tenant-isolation.md) | Tenant isolation lives in one scoped repository | 0 |
| [0002](0002-idempotent-session-intake.md) | Idempotent session intake via unique key + savepoint | 0 |
| [0003](0003-append-only-facts-conflict-rule.md) | Append-only facts, conflict rule v1 | 0 |
| [0004](0004-single-write-path-and-provenance.md) | One write path for facts, provenance on every fact | 0 |
| [0005](0005-sync-sqlalchemy-and-databases.md) | Sync SQLAlchemy; Postgres is the target, SQLite for dev/tests | 0 |
| [0006](0006-llm-provider-layer.md) | Provider-agnostic LLM layer with validate-and-repair | 1 |
| [0007](0007-question-planner.md) | Question planner: fallback, caps in code, untrusted input | 1 |
