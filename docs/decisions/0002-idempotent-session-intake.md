# 0002 Idempotent session intake via unique key + savepoint
Status: accepted (slice 0)

**Context.** The admin panel may call `POST /v1/sessions` twice for one task; that must not create two sessions,
even when the calls are concurrent.

**Decision.** Unique constraint on `(tenant_id, idempotency_key)`. Intake first looks the key up; if absent it
inserts inside a savepoint. If a concurrent call won, the unique violation is caught and the winner's row is
returned (200 instead of 201). The same key with a different task or end user returns 409.

**Alternatives.** `INSERT ... ON CONFLICT DO NOTHING` (Postgres/SQLite specific syntax; the savepoint approach
is portable). Application-level locks (do not survive multiple workers).

**Consequences.** The race path is tested by forcing the pre-check to miss (`test_insert_race_falls_back_to_existing`).
