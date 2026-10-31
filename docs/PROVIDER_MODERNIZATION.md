# Aeonith provider adapters

Aeonith ships explicit, dependency-free HTTP provider adapters in
`aeonith/providers.py`. The Chat Completions transport preserves the v0.1
legacy request mode, and v0.2 adds an opt-in Responses transport and
model-specific parameter switches. These are source capabilities, not a
deployed external API or proof of live model compatibility.
The public contract remains `provider.review(payload) -> dict`, and the core
still independently validates output, quotations and provenance before emitting
a completed critique.

## Implemented provider modes

| Provider | Endpoint | CLI selection | Output token request | JSON request |
|---|---|---|---|---|
| Existing chat-compatible | Explicit URL ending in `/chat/completions` | `--provider openai-compatible` | `--token-field max_tokens` (legacy default), `max_completion_tokens`, or `none` | Optional `--json-mode` |
| OpenAI Responses API | Explicit URL ending in `/responses` | `--provider openai-responses` | `max_output_tokens` | `text.format.type=json_object` by default; `--no-json-mode` opt-out |

The adapters **do not auto-detect** a model's capabilities or rewrite the
endpoint path. For modern OpenAI Chat Completions models, choose the supported
`--token-field max_completion_tokens`, and use `--omit-temperature` where the
selected model does not accept sampling temperature. Older compatible servers
retain the original defaults. JSON mode asks the model to return valid JSON;
**it does not guarantee Aeonith's exact result schema**. That is why `core.py`
validates every candidate and rejects unverifiable evidence or incomplete
shapes.

## CLI examples

Replace the model name and URL only after selecting a provider and reviewing
the data-sharing consequences for the manuscript. The following commands are
illustrative; no live API was contacted during implementation.

```bash
python -m aeonith review --input manuscript.json \
  --provider openai-responses \
  --url https://api.openai.com/v1/responses \
  --model YOUR_SUPPORTED_MODEL
```

```bash
python -m aeonith review --input manuscript.json \
  --provider openai-compatible \
  --url https://api.openai.com/v1/chat/completions \
  --model YOUR_SUPPORTED_CHAT_MODEL \
  --token-field max_completion_tokens --omit-temperature --json-mode
```

To authenticate explicitly, place the secret in the environment variable named
by `--api-key-env` (default `AEONITH_PROVIDER_API_KEY`); never write a secret to
input JSON, the command line, logs or a repository file. Provider selection is
opt-in; setting environment variables alone never triggers an API call. The
local unit tests use fake in-memory HTTP transport and never need API keys.

## Privacy and error semantics

- Credential-bearing requests are HTTPS-only. Plain HTTP is accepted only for
  unauthenticated loopback development endpoints. Redirects are refused rather
  than forwarding a bearer token or manuscript to a changed host.
- Responses API calls send `store: false` and no tool configuration, preventing
  request-controlled tools and disabling server response-state storage. **This
  is not a zero-data-retention guarantee**; consult the selected provider's
  applicable retention/privacy terms before sending private manuscripts.
- The transport has a 4 MB response body cap, a configurable bounded timeout,
  and bounded output-token request. It rejects nonfinite JSON, refusal content,
  incomplete Responses API status, missing assistant text, unexpected tool
  calls, non-assistant chat replies, and chat content not finished as text.
- Failure stays a machine-readable `provider_error` through `core.critique`;
  no fabricated literary analysis is substituted. The transport has no retry
  mechanism, tool execution, vector store, file-upload, caching or telemetry.

## Official API documentation grounding

- OpenAI Chat Completions create parameters: `max_completion_tokens` replaces
  the deprecated `max_tokens` for compatible models, and a JSON object response
  format can be requested:
  https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- OpenAI Responses create request: `instructions`, `input`,
  `max_output_tokens`, `store`, and `text.format`:
  https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI Structured Outputs guide and JSON mode distinctions:
  https://developers.openai.com/api/docs/guides/structured-outputs

Compatibility is model-specific and may evolve. These sources verify the
request fields, not that any chosen model will accept all flags, reproduce all
14 critical lenses faithfully, or produce high-quality real-world criticism.

## Source verification

The adapters and their regression tests are included in the repository.
Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q aeonith
```

Release qualification still requires deliberate live model testing with a
non-sensitive manuscript and a human review of the literary judgment quality.
The mocked tests prove request construction and fail-closed protocol parsing,
not upstream inference quality, provider uptime, pricing, or data residency.
