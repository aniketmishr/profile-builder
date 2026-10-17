# 0003 Append-only facts, conflict rule v1
Status: accepted (slice 0)

**Context.** A new value for an existing key must supersede the old one, but history must remain, with its source session.

**Decision.** `profile_facts` is append-only. Exactly one row per `(tenant, end_user, category, key)` has
`is_current = true`, enforced by a partial unique index. Writing a new value flips the old row
(`is_current=false`, `superseded_by`, `superseded_at`) and inserts the new one in one transaction.
Rule v1: the latest write wins; the same value again is a no-op; duplicate keys inside one batch keep the
highest confidence (later wins ties). Writers are serialised per profile with a row lock on `end_users`.
`end_users.profile_version` increments on every change (ETags, cache invalidation, future webhook).

**Alternatives.** Overwrite in place (loses history). Confidence-first resolution (an old confident guess
could beat a newer, agent-confirmed fact). Graph/temporal stores such as Graphiti (more power than needed).

**Consequences.** Multi-valued keys (several avoided channels) overwrite each other unless the value is a list.
Revisit with a per-key cardinality setting if needed.
