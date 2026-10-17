# 0006 Provider-agnostic LLM layer with validate-and-repair
Status: accepted (slice 1)

**Context.** The brief wants the LLM behind one small interface, schema-valid output, and graceful handling of
provider failures. Free tiers and model names change often.

**Decision.** A provider implements one method, `complete_json(system, user) -> str`. `generate_structured()`
(in `app/llm/base.py`) parses the text, validates it against a Pydantic model and, on failure, asks once more
showing the validation errors; then it raises `LLMError`. The schema is placed in the prompt text, so any
provider works without relying on its own schema dialect. `GeminiProvider` uses plain `httpx` (no SDK), sends
the key in a header, retries once on 429/5xx/transport errors, and wraps all failures in `LLMError`.
`LLM_PROVIDER=none` (default) means no provider. The model id is a required setting, with no hardcoded
default, because model names go stale.

**Alternatives.** Provider-native structured output / tool calling (each differs; schema subsets are limited).
An SDK per provider (heavier dependencies). LangChain (not needed for two prompts).

**Consequences.** Adding a provider is one small class plus a line in `get_llm()`. Parsing and repair are tested once.
The Gemini request shape is verified with a mocked transport only; the first real call happens on your machine.
