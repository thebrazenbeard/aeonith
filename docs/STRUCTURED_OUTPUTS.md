# Optional strict structured-output mode (local models)

Aeonith supports an **explicit**, model-dependent JSON Schema request mode in
its HTTP transport code. This is additive to the `aeonith.review.v1` contract.
Under the **$0.00 additional-spend policy**, only local inference is supported;
the legacy remote Responses research is retained solely to explain the
protocol shape. Not every local runner or GGUF model can honor strict schemas.

## Selection

From the repository root, with a previously installed local model already
running on the same computer:

```bash
unset AEONITH_PROVIDER_API_KEY
python -m aeonith review --input examples/microfiction.json \
  --provider local-openai-compatible \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --model local \
  --structured-outputs
```

This is an example, **not a live compatibility check**. The local model may
reject `json_schema`, sampling settings, or token fields; Aeonith reports an
error rather than silently falling back to a remote service. Never configure
a paid provider to work around local output-format incompatibility.

## Contract and trust boundaries

- Chat Completions uses `response_format.type=json_schema`, with a
  `json_schema` object containing `name`, `strict: true`, and `schema`.
- Historical Responses transport used `text.format.type=json_schema` with
  corresponding keys; it is **not** an approved runtime mode under the
  zero-cost operating policy.
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

`tests/test_provider_structured.py` documents request shapes, malformed input
rejection, and core quote validation with in-memory HTTP fakes. Tests for old
remote transports are historical protocol coverage, **not** authorization to
invoke them. No actual local model inference or privacy setting was tested.

- [Official OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs):
  supported strict JSON Schema subset, nested `anyOf`, required keys and
  `additionalProperties` behavior.
- [Chat Completions API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  `response_format.json_schema`.
- [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create):
  `text.format`.

The [KoboldCpp API reference](https://github.com/LostRuins/koboldcpp.net/blob/main/src/content/docs/docs/api/endpoints.mdoc)
describes the local Chat Completions route. Model support can change; a
non-sensitive **local** qualification run and human review remain necessary.
