# 0010 Extraction pipeline: validated proposals, persisted run, safe fallback
Status: accepted (slice 3)

**Context.** After the debrief, the agent's answers must become structured facts (category, key, value, confidence,
evidence quote, source session, timestamp) that are always schema-valid and never invented. Extraction must survive
a closed tab or a crashed process, and a provider outage must not lose what the agent said.

**Decision.**
- One LLM call (`extractor_v1`) over the answered questions only. Output is validated against a Pydantic schema
  (`value` is a string or list of strings; `category` is the fixed enum).
- Validation is code, not trust: every fact needs an evidence quote that appears inside ONE agent answer
  (case, punctuation and whitespace insensitive; questions and task context do not count). Facts are also dropped
  for confidence below 0.5, an unusable key, an empty value, a duplicate (category, key) (highest confidence wins),
  or exceeding `MAX_EXTRACTED_FACTS`. Rejections and reasons are stored in `extractions.dropped`.
- Keys are normalised to snake_case. The prompt lists canonical keys to keep naming consistent, but new keys are allowed.
- Confidence follows a rubric in the prompt (explicit 0.9+, hedged 0.7 to 0.89, implied 0.5 to 0.69, otherwise omit).
- Persisted run: `extractions` (one row per session; status running, ready, confirmed, failed; attempt;
  the exact prompt in `llm_input`, the model's reply in `llm_output`) and `extracted_facts` (the proposals).
  It starts in the background when the debrief completes (`AUTO_EXTRACT`). A re-run (`POST .../extraction`) is allowed
  when ready or failed, or when a run has been "running" longer than `EXTRACTION_STALE_SECONDS` (presumed dead).
  A crash marks the run `failed` instead of leaving it stuck.
- Fallback: if there is no provider, the call fails, or every proposal fails validation, the agent's own answers are
  offered as `notes` facts (their literal words, confidence 0.5). Nothing the agent said is lost, nothing is invented.
- If nothing was answered (all skipped), no LLM call is made.

**Alternatives.** Trusting the model's quotes (they can be fabricated). A different model call to verify the first
(cost, and still a model). Extracting turn by turn (more calls, fragmentary context). Pre-extracting from the customer
transcript excerpt (it is the customer's speech, not the agent's; evidence must be the agent's words).

**Consequences.** Evidence checking proves a quote exists, not that the value is the right reading of it; the agent's
confirmation step covers that. The background run is in-process: if the server dies mid-run the row stays `running`
until it is retried. A proper worker with a jobs table (a later slice) would remove that. Prompt changes mean a new
`extractor_v2.md` plus a constant bump. The prompt has been tested with scripted outputs only, not a live model.
