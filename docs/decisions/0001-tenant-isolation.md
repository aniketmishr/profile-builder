# 0001 Tenant isolation lives in one scoped repository
Status: accepted (slice 0)

**Context.** The brief makes isolation non-negotiable and wants it enforced in one place, not sprinkled
through handlers, with a test proving tenant A cannot touch tenant B.

**Decision.** `app/repo.py` is the only module that queries tenant data. `ScopedRepo` is built from the
tenant resolved from the API key (`deps.get_repo`); its methods take no tenant argument and every query
goes through `_select()`, which adds the tenant filter. The schema backs this up: `agents` and `end_users`
have composite keys `(tenant_id, id)`, and a fact's end user and source session must exist in the same
tenant (composite foreign keys). Cross-tenant lookups return 404, not 403, so existence never leaks.
The body `tenant_id` on intake must equal the key's tenant (403 otherwise).

**Alternatives.** Filtering in each handler (easy to forget). Postgres row-level security
(`SET LOCAL app.tenant_id`): good defense in depth, not built yet because SQLite is also supported.

**Consequences.** New data access must be added as a `ScopedRepo` method. `tests/test_isolation.py`
must keep covering every new endpoint.
