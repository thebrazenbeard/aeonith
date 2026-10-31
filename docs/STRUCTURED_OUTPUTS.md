# Optional strict structured-output mode

Aeonith supports an **explicit**, model-dependent JSON Schema request mode in
both built-in HTTP adapters. This is additive to the existing `aeonith.review.v1`
contract. The earlier Chat Completions defaults and Responses JSON-object mode
remain unchanged unless `--structured-outputs` is selected.

## Selection

From the repository root, after choosing a trusted endpoint/model and
separately deciding whether the manuscript may be disclosed:

```bash
python -m aeonith review --input request.json \
  --provider openai-responses \
  --url https://api.openai.com/v1/responses \
  --model YOUR_COMPATIBLE_MODEL --structured-outputs
```

```bash
python -m aeonith review --input request.json \
  --provider openai-compatible \
  --url https://api.openai.com/v1/chat/completions \
  --model YOUR_COMPATIBLE_CHAT_MODEL \
  --token-field max_completion_tokens --omit-temperature \
  --structured-outputs
```

These are examples, **not live compatibility checks**. The adapters do not
infer which models support strict schemas. The selected model/service may
reject `json_schema`, sampling settings, or token fields, and Aeonith reports
a provider error rather than silently falling back to an unrequested mode.

## Contract and trust boundaries

- Chat Completions uses `response_format.type=json_schema`, with a
  `json_schema` object containing `name`, `strict: true`, and `schema`.
- Responses uses `text.format.type=json_schema` with the corresponding
  `name`, `strict: true`, and `schema` keys; `store: false` remains set.
- The generated JSON Schema is a bounded root object; every object sets
  `additionalProperties: false` and requires each declared field.
- It has one lens-review array with a selected-canonical-lens enum, an analysis,
  a basis enum, literal quote/reference anchors via nested `anyOf`, limitations,
  synthesis, challenges, uncertainties, and nullable assessment.
- It deliberately omits unsupported fine-tuning-specific constraints such as
  string and array size keywords. **The core** enforces exact lens coverage,
  bounded fields, quote occurrence and input evidence IDs after transport.
- Output-schema adherence is **not** independent evidence verification, insight,
  source authenticity, historical accuracy, consent, or GPT behavioral parity.

The strict mode rejects missing, duplicate, or unknown selected lenses before
connecting to a provider. Refusal, incomplete output and tool-call states stay
fail-closed. The mode uses no tools, retrieval, uploaded knowledge, local API
keys, or automatic network calls.

## Verification and official sources

`tests/test_provider_structured.py` checks request shape for both providers,
default backward compatibility, malformed input rejection before network,
continued core quote validation, and CLI selection with in-memory HTTP fakes.
No model inference or privacy policy was tested.

- [Official OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs):
  supported strict JSON Schema subset, nested `anyOf`, required keys and
  `additionalProperties` behavior.
- [Chat Completions API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  `response_format.json_schema`.
- [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create):
  `text.format`.

Model support and upstream semantics can change; a live qualification run with
non-sensitive work and explicit data-sharing permission remains necessary.
