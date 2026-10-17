# 0011 Confirm step: default keep, explicit edit/discard, one transaction
Status: accepted (slice 3)

**Context.** Before saving, the agent sees a compact summary and can confirm, edit or discard individual facts.
Saving must be all-or-nothing and must go through the single write path (ADR 0004).

**Decision.** `POST /v1/sessions/{id}/extraction/confirm` takes optional `decisions` (`keep`, `edit` with a new value,
`discard`). Facts not listed are kept: pressing Save is the confirmation, discarding is deliberate. Validation of all
decisions happens before anything is written. Kept and edited facts are saved with `services.apply_facts(commit=False)`,
and the extracted-fact statuses, the extraction status (`confirmed`) and the session status (`profile_saved`) change in
the same transaction, so a failure leaves everything as it was and the agent can retry.
An edited fact gets confidence 1.0 (the agent's own correction), `agent_edited: true` and the original value in its
provenance, which also records the prompt version, model, source and attempt. This realises "latest confirmed fact wins"
(ADR 0003): only confirmed facts ever reach the profile. A second confirm returns 409.

**Alternatives.** Require a decision for every fact (tedious API). Save immediately and let the agent undo (violates
"confirm before saving"). Per-fact PATCH calls (many round trips, no atomicity).

**Consequences.** `apply_facts` gained per-fact provenance and a `commit` flag. Edits change the value only (not
category or key). The edit rate (`agent_edited`) is a ready-made extraction-quality metric for the later dashboard.
