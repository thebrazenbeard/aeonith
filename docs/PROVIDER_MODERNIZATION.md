# Aeonith provider adapters — local-only operating policy

**Current operating rule: $0.00 additional spending, no cloud inference.**
Aeonith's supported CLI/service selection is `local-openai-compatible`,
with a literal loopback endpoint and no API key. Earlier remote adapter
research remains in this document for historical protocol context, **not** as
instructions to use a paid service. No remote fallback is authorized.

Aeonith ships dependency-free HTTP transport code in `aeonith/providers.py`.
Earlier revisions implemented general Chat Completions and Responses
transports, still useful as source-level compatibility references. The
supported zero-cost path constrains the selected Chat Completions destination
to a local endpoint; no actual model qualification is implied.
The public contract remains `provider.review(payload) -> dict`, and the core
still independently validates output, quotations and provenance before emitting
a completed critique.

## Implemented provider modes

| Adapter | Endpoint | Status | Output token request | JSON request |
|---|---|---|---|---|
| Local Chat Completions | Exact local `/v1/chat/completions` URL | **Supported:** `--provider local-openai-compatible` | `max_tokens` (some runners expose compatible alternatives) | JSON mode by default; `--no-json-mode` to disable, or `--structured-outputs` if supported |
| General Chat Completions | Arbitrary explicit HTTP URL | Historical transport implementation; not an approved runtime selection | Legacy `max_tokens` or model-dependent alternatives | Historical compatibility behavior |
| OpenAI Responses | General remote `/responses` URL | Historical transport implementation; **not** an approved runtime selection | `max_output_tokens` | `text.format` requests |

The adapters **do not auto-detect** a model's capabilities or rewrite the
endpoint path. The supported local CLI offers `--omit-temperature` if a
particular runner rejects that field and `--no-json-mode` if it rejects JSON
response-format requests. Older generic transport classes retained legacy
token-field variants for research, but these are not active CLI selections.
JSON mode asks the model to return valid JSON;
**it does not guarantee Aeonith's exact result schema**. That is why `core.py`
validates every candidate and rejects unverifiable evidence or incomplete
shapes.

## Approved CLI example

Use a **previously installed and running** compatible local model (for example
KoboldCpp on your own computer). The example makes no cloud request; it will
return a provider error if the local server is unavailable. Choose a model
name that your local runtime accepts.

```bash
unset AEONITH_PROVIDER_API_KEY
python -m aeonith review --input examples/microfiction.json \
  --provider local-openai-compatible \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --model local
```

Do not configure provider keys or saved unrelated credentials. Provider
selection is opt-in; setting environment variables alone must not trigger a
request. The unit tests use controlled fake transport and never need API keys.

## Privacy and error semantics

- Approved local requests use no provider credential and a literal loopback
  HTTP endpoint. Redirects and inherited HTTP(S) proxy settings are refused,
  preventing accidental forwarding to a different host.
- Historical Responses code includes `store: false`, which is **not** a
  zero-retention guarantee; it must not be used as a justification to send
  manuscripts to a cloud provider.
- The transport has a 4 MB response body cap, a configurable bounded timeout,
  and bounded output-token request. It rejects nonfinite JSON, refusal content,
  incomplete Responses API status, missing assistant text, unexpected tool
  calls, non-assistant chat replies, and chat content not finished as text.
- Failure stays a machine-readable `provider_error` through `core.critique`;
  no fabricated literary analysis is substituted. The transport has no retry
  mechanism, tool execution, vector store, file-upload, caching or telemetry.

## Original protocol research sources (not deployment instructions)

- OpenAI Chat Completions create parameters: `max_completion_tokens` replaces
  the deprecated `max_tokens` for compatible models, and a JSON object response
  format can be requested:
  https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- OpenAI Responses create request: `instructions`, `input`,
  `max_output_tokens`, `store`, and `text.format`:
  https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI Structured Outputs guide and JSON mode distinctions:
  https://developers.openai.com/api/docs/guides/structured-outputs

For the supported local runner, consult the [KoboldCpp endpoint
documentation](https://github.com/LostRuins/koboldcpp.net/blob/main/src/content/docs/docs/api/endpoints.mdoc)
and verify its `/v1/chat/completions` behavior yourself. Protocol research
sources verify possible request fields, not that a particular local model
accepts every flag, reproduces all fourteen lenses, or generates useful
literary criticism.

## Source verification

The adapters and their regression tests are included in the repository.
Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q aeonith
```

Release qualification still requires deliberate **local** model testing with a
non-sensitive manuscript and human review of literary judgment quality.
The mocked tests prove request construction and fail-closed protocol parsing,
not actual inference quality, local model availability, or model-runner privacy.
