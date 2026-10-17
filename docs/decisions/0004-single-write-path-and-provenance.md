# 0004 One write path for facts, provenance on every fact
Status: accepted (slice 0)

**Context.** Facts will come from hand-written dev calls now and LLM extraction plus agent confirmation later.
The conflict rule must not diverge between them, and "why was this fact saved" must be answerable.

**Decision.** `services.apply_facts()` is the only function that writes facts. Callers pass `provenance`
(JSON). Manual writes record `{"origin": "manual"}`; extraction will record the prompt version, model and raw
tool call. It validates that the source session belongs to the same end user and tenant.

**Alternatives.** Separate write code per source (rule drift). Storing provenance in a side table (more joins, no benefit yet).

**Consequences.** The extractor and the confirm step must call `apply_facts`, never insert rows directly.
