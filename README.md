# Aeonith

Aeonith is an independently implemented, evidence-aware literary critic inspired by the observable behavior of [Aeonith, the Transcendent Critic](https://chatgpt.com/g/g-67f64b3b94348191b6f6ee4a83135b5a-aeonith-the-transcendent-critic), a custom ChatGPT GPT. It is **not** an export of that GPT's private instructions, reference files, model weights, or hidden configuration.

**Operating rule: $0 in new spending.** This repository is designed to run on hardware and a local model you already have. It does not require a paid inference API, subscription, hosted database, or deployment platform. We do **not** enable paid services, even behind a nominal spending budget. Optional public HTTPS access via an existing, eligible **free** Tailscale Funnel configuration is separate from the localhost default; no active public deployment is advertised until independently verified.

Aeonith has two separate capabilities:

1. A complete, dependency-free **review contract, manuscript-processing workflow, and critical-method prompt set**, testable without any model calls.
2. A **local web interface and authenticated HTTP API** that can request genuine model-generated criticism **only after** you explicitly configure a running, local compatible model. A healthy web page or green test suite alone is not a model-backed critique.

## What works

- Python 3.11+ standard-library package, JSON CLI, plain-text/Markdown manuscript workflow, and Markdown report renderer.
- Fourteen critical lenses: psychological, literary/thematic, narrative structure, character development, historical/cultural, philosophical, genre-specific, stylistic, sociological, moral/ethical, symbolic, reader-response, linguistic, and comparative.
- Typed review results with a synthesis, lens-by-lens interpretation, challenges, uncertainties, evidence pointers and candid insufficient-evidence outcomes.
- Source-exact quoted-passage checks and caller-supplied evidence-reference checks. A quote's presence **does not establish that the interpretation is true**.
- Optional exact-quote offset and fingerprint sidecar; deterministic planning for long manuscripts using bounded excerpts, **not** automatic whole-book comprehension.
- Local evaluation fixtures and a blinded human-evaluation workflow. Structural acceptance tests are **not** measures of literary quality.
- Opt-in model adapters, including a constrained local OpenAI-style Chat Completions route. No invented critiques on missing-provider, rejected-input, failed-model, or invalid-output paths.
- A same-origin browser interface with manuscript editor, lens selection, and a token-protected local review endpoint. The default is provider-disabled and loopback-only.
- An optional, explicit `AEONITH_FUNNEL_ORIGIN` allowlist for one Tailscale `.ts.net` HTTPS hostname. The listener and GGUF model remain bound to localhost, and review authentication still applies. This code path must be separately verified on the actual host before calling it a live public service.

**Not yet proven:** the quality of judgments from your particular GGUF model, parity with the original GPT, fidelity of third-party citation assertions, consistency across repeated generations, or a live end-to-end model run on your machine. A local model can be too small, too slow, context-limited, or unable to emit Aeonith's strict JSON shape; in those cases the application should report failure, not pretend to have completed a critique.

## Run locally at no additional service cost

Use an existing local model runner such as [KoboldCpp](https://github.com/LostRuins/koboldcpp) with a GGUF text model you already possess or have permission to use. KoboldCpp documents an OpenAI-compatible API at its local `/v1` route, normally port `5001`. Use a model you are licensed to run; Aeonith does not ship or acquire model weights.

1. Launch your own KoboldCpp model **locally** and verify its API is listening on `127.0.0.1:5001`. Its Chat Completions endpoint is ordinarily `http://127.0.0.1:5001/v1/chat/completions` ([upstream endpoint reference](https://github.com/LostRuins/koboldcpp.net/blob/main/src/content/docs/docs/api/endpoints.mdoc)). Keep its listener off public networks.
2. From this repository, configure only the local endpoint and generate a fresh service token. No paid API key is needed:

   ```bash
   export AEONITH_SERVICE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
   export AEONITH_PROVIDER_KIND=local-openai-compatible
   export AEONITH_PROVIDER_URL=http://127.0.0.1:5001/v1/chat/completions
   export AEONITH_PROVIDER_MODEL=local
   export AEONITH_ENABLE_LIVE_REVIEWS=true
   unset AEONITH_PROVIDER_API_KEY
   python3 -m aeonith.local_server
   ```

   On Windows PowerShell, the equivalent is:

   ```powershell
   $bytes = New-Object byte[] 32
   [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
   $env:AEONITH_SERVICE_TOKEN = [Convert]::ToBase64String($bytes)
   $env:AEONITH_PROVIDER_KIND = 'local-openai-compatible'
   $env:AEONITH_PROVIDER_URL = 'http://127.0.0.1:5001/v1/chat/completions'
   $env:AEONITH_PROVIDER_MODEL = 'local'
   $env:AEONITH_ENABLE_LIVE_REVIEWS = 'true'
   Remove-Item Env:AEONITH_PROVIDER_API_KEY -ErrorAction SilentlyContinue
   python -m aeonith.local_server
   ```

3. On the **same computer**, open `http://127.0.0.1:8765/` and enter that token in the editor. The token is kept in page memory, not browser persistent storage. The service binds to `127.0.0.1` by default; do not expose it publicly. Stop it with `Ctrl+C`.

`AEONITH_PROVIDER_MODEL=local` is a model label for a simple single-model KoboldCpp instance, not a model download instruction. If your runner requires a particular model ID, use the ID it exposes. Local model interoperability and output quality must be checked with a harmless test passage; not all compatible APIs support JSON mode or structured output equally. The service deliberately does **not** fall back to a remote model if local inference fails.

If a local model is not already running, you can still run the library, tests, source planner, and offline evaluation without any network calls. To inspect the browser shell with reviews disabled, leave `AEONITH_ENABLE_LIVE_REVIEWS` unset and run `python3 -m aeonith.local_server` after configuring a strong service token.

The exact HTTP routes, environment options, security limitations, and local verification steps are in the [self-hosted service runbook](docs/SERVICE_DEPLOYMENT.md). For an **optional public URL**, see the [Tailscale Funnel runbook](docs/TAILSCALE_FUNNEL.md); it explicitly requires a no-charge eligible account, hardened security checks, and a real HTTPS probe. See [release gates](docs/RELEASE_GATES.md) before describing a machine-specific model setup as qualified.

## Try the CLI without a model

From the source checkout, with Python 3.11 or later:

```bash
python3 -m aeonith review --input examples/microfiction.json
python3 -m aeonith.workflow --input draft.md --title "A draft"
```

With no provider chosen, review status is `provider_unavailable` and the command exits `3`. This is intentional: prompt preparation and structural validation without a language model do not constitute literary criticism. Replace `draft.md` with an existing UTF-8 `.txt` or `.md` manuscript file for the workflow command.

To use an explicitly selected **local** Chat Completions endpoint from the JSON CLI:

```bash
unset AEONITH_PROVIDER_API_KEY
python3 -m aeonith review \
  --input examples/microfiction.json \
  --provider local-openai-compatible \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --model local
```

Or from a real manuscript into a new Markdown file (Aeonith will never overwrite an existing output):

```bash
python3 -m aeonith.workflow --input draft.md --title "Draft" \
  --provider local-openai-compatible \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --model local --output critique.md
```

Only run these model-backed commands when the local runner is actually available. The selected local adapter rejects remote endpoints and keeps network protections (including no HTTP redirects or inherited proxy forwarding). The legacy generic remote adapters are **not** an approved route to paid inference.

For programmatic integration:

```python
from aeonith import critique

request = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Draft", "text": "The door opened, but nobody entered."},
}
result = critique(request, provider=my_explicitly_configured_provider)
```

The injected provider implements `review(payload: dict) -> dict`. With no provider, `critique(request)` returns a truthful `provider_unavailable` status. The independent core validates output structure and exact support quotations; it cannot independently determine whether a model's reasoning is good.

## Browser and HTTP contract

| Route | Behavior |
| --- | --- |
| `GET /` | Local manuscript editor and static assets, no embedded secrets |
| `GET /healthz` or `/api/health` | Liveness and configuration-readiness indicator, **not** proof of a successful model call |
| `POST /api/review` or `/v1/critique` | Strict `aeonith.review.v1` request; strong server-held bearer token, bounded UTF-8 JSON, explicit operator model selection |

The HTTP boundary checks authorization **before reading the manuscript body**. It caps request size and excerpt length, rejects unsupported methods and caller-specified endpoints, and avoids echoing manuscript text or secrets in error responses. If the model is unavailable or produces invalid output, the UI displays that failure. Browser code does not store manuscript content or bearer tokens in cookies, `localStorage`, or `sessionStorage`.

Loopback is a meaningful privacy boundary but not perfect isolation: other software with access to the same host may contact local services, local browser extensions may read page contents, and model process logs may contain text depending on the model runner's settings. **Do not publish the localhost port directly.** The optional Tailscale Funnel path exposes only Aeonith's HTTPS frontend after exact-origin opt-in and security verification; it is **publicly reachable** and is not a multi-user authorization system. Aeonith does not supply a durable cross-process rate ledger, cloud SLA, or independent production threat review.

## More capabilities and their limits

- [Critical lens methods](docs/LENS_METHODS.md) describe deliberately different question sets and textual grounding expectations.
- [Long-form planning](docs/LONGFORM.md) preserves source offsets across bounded excerpts; it does **not** synthesize unseen chapters.
- [Evidence/source anchors](docs/SOURCE_ANCHORS.md) cover quoted text and ambiguous repeated passages, not attribution truth.
- [Structured output behavior](docs/STRUCTURED_OUTPUTS.md) documents provider-specific compatibility issues and the independent validation layer.
- [Reader workflow](docs/READER_WORKFLOW.md) documents local text input and report generation.
- [Offline evaluation](evaluation/README.md) describes human scoring, blinded comparisons, and machine-checkable structural warnings. No fixture test can establish original-GPT parity or human-level criticism.
- [Public functional specification](docs/AEONITH_PUBLIC_SPEC.md) distinguishes observed GPT behavior from this new implementation. [Integration research](docs/INTEGRATION_RESEARCH.md) and [research quality](docs/RESEARCH_QUALITY.md) are design references rather than runtime quality certificates.

An experimental [host boundary](docs/HOST_BOUNDARY.md) and source-only `integrations/host_gate.py` are **not** deployed identity, permission, metering, or ecosystem mutation controls. Aeonith analyses are **advice**, not instructions to rewrite manuscripts or change other repositories automatically. Private knowledge assets and GPT activation material are not bundled.

## Test and qualify

```bash
python3 -m unittest discover -s tests -v
```

The repository's Python tests use controlled local providers and deterministic fixtures; they must not incur model or cloud charges. A real local model qualification requires a separately observed, harmless passage, matching selected lenses, valid JSON, source-exact quotes, useful counterreadings, and repeated human review. Record the local runtime/model, settings, exact source commit, and outcome. Never describe a structurally passing response alone as literary validation.

## Rights and licensing

This repository currently has no published license. Publicly readable code is **not automatically open source**, and no rights to redistribute the original GPT's attached reference corpus are implied. Choose a license and review third-party asset rights before redistribution.
