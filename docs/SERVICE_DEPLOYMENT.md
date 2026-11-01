# Aeonith local-service runbook — no paid infrastructure

Aeonith's supported operating model is **self-hosted on an already-owned computer with zero new service/API spending**. The former Vercel shell and paid-provider pilot are retired; account deletion means historical deployment `READY` records are not evidence of a current live endpoint. No Vercel account, Gateway, Upstash Redis database, subscription, or paid model key is part of this setup. An optional existing **free-plan Tailscale Funnel** can expose the web interface over public HTTPS; it is not enabled by default and requires separate verification.

The source includes a browser UI and a stdlib Python server, but it does not ship model weights. A provider-disabled shell is not a functioning AI critic. Actual criticism requires a locally running, capable, compatible model.

## Prerequisites

- Python 3.11+ and an Aeonith source checkout on a computer you control.
- For inference, an **already available** local text model with an OpenAI-compatible Chat Completions API. [KoboldCpp](https://github.com/LostRuins/koboldcpp) with an authorized GGUF model is one option. Consult [its API endpoint documentation](https://github.com/LostRuins/koboldcpp.net/blob/main/src/content/docs/docs/api/endpoints.mdoc); the usual route is `http://127.0.0.1:5001/v1/chat/completions`.
- No provider API key and no cloud credentials. Do not use saved unrelated keys or tunneling credentials merely because they exist.

## Start the service

From the repository root, on the same computer as the local model:

```bash
# Start the model runner separately, with its API bound to the local machine.
export AEONITH_SERVICE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AEONITH_PROVIDER_KIND=local-openai-compatible
export AEONITH_PROVIDER_URL=http://127.0.0.1:5001/v1/chat/completions
export AEONITH_PROVIDER_MODEL=local
export AEONITH_ENABLE_LIVE_REVIEWS=true
unset AEONITH_PROVIDER_API_KEY

python3 -m aeonith.local_server --host 127.0.0.1 --port 8765
```

On Windows PowerShell, set the same values for the current terminal session:

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$env:AEONITH_SERVICE_TOKEN = [Convert]::ToBase64String($bytes)
$env:AEONITH_PROVIDER_KIND = 'local-openai-compatible'
$env:AEONITH_PROVIDER_URL = 'http://127.0.0.1:5001/v1/chat/completions'
$env:AEONITH_PROVIDER_MODEL = 'local'
$env:AEONITH_ENABLE_LIVE_REVIEWS = 'true'
Remove-Item Env:AEONITH_PROVIDER_API_KEY -ErrorAction SilentlyContinue
python -m aeonith.local_server --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` on that computer. Enter the freshly generated bearer token to submit a passage. The UI is same-origin. It does not persist that token or manuscript text in browser storage. Do not paste the token into a publicly visible terminal transcript, issue tracker, chat, screenshot, or repository file.

The local server listens on loopback only, normally `127.0.0.1:8765`; it rejects a non-loopback host rather than offering a LAN mode. **Do not expose the local port directly.** For an optional public HTTPS endpoint, use the [separate Tailscale Funnel runbook](TAILSCALE_FUNNEL.md): it requires an exact Tailscale hostname allowlist, local resource protections, a qualifying $0 Tailscale account, and a verified external HTTPS test. A public Funnel is not equivalent to a private tailnet connection.

If the model is not ready, leave `AEONITH_ENABLE_LIVE_REVIEWS` unset or set it to `false` to run only the UI and health endpoint. Review requests fail closed rather than inventing criticism. A different local model runtime may require a different local endpoint and model label; confirm exact compatibility before enabling it. In simple KoboldCpp single-model mode the model label may be arbitrary, whereas router mode may select by name.

## Configuration

| Setting | Behavior |
| --- | --- |
| `AEONITH_SERVICE_TOKEN` | Required strong server-side ASCII token, at least 32 characters; browser sends it as a bearer token for reviews |
| `AEONITH_ENABLE_LIVE_REVIEWS` | Only literal `true` enables model dispatch; absent/`false` is safe disabled default |
| `AEONITH_PROVIDER_KIND` | Set `local-openai-compatible` for local-only inference |
| `AEONITH_PROVIDER_URL` | Full local HTTP URL, normally `http://127.0.0.1:5001/v1/chat/completions`; never a caller-controlled endpoint |
| `AEONITH_PROVIDER_MODEL` | Identifier accepted by the already-running local model server |
| `AEONITH_MAX_LENSES` | Optional selected-lens ceiling, 1–14 (default 14); not a billing budget |
| `AEONITH_MAX_OUTPUT_TOKENS` | Optional per-call response limit, 256–8192 (default 4096) |
| `AEONITH_PROVIDER_TIMEOUT_SECONDS` | Optional model response timeout, 1–50 seconds (default 45) |
| `AEONITH_LOCAL_JSON_MODE` | `true` (default) requests JSON-mode Chat Completions; set literal `false` if your existing local runner does not support `response_format` |
| `AEONITH_STRUCTURED_OUTPUTS` | Literal `false` (default) or `true`; strict schema mode requires a compatible local runner and model |
| `AEONITH_FUNNEL_ORIGIN` | Optional exact HTTPS origin `https://machine.tailnet.ts.net` for the user's own Tailscale Funnel. Unset by default; never a wildcard or arbitrary domain |

**Do not configure** any paid-provider credential, remote model URL, Gateway OIDC, Vercel runtime marker, external admission database, or billing limit. No financial spending allowance is contemplated: the hard additional-service spending limit is **$0**. Local inference does not require Redis because the server is single-process and loopback-bound by default; the optional public Funnel is still **not** a multi-user identity system or globally rate-limited internet deployment.

## Route and security checks

| Route | Expected result |
| --- | --- |
| `GET /` | Local manuscript editor and static assets |
| `GET /healthz` and `GET /api/health` | JSON process health and `review_configured` boolean; readiness does not imply a successful inference request |
| `POST /api/review` and `POST /v1/critique` | Authenticated bounded JSON review; actual inference only if explicitly enabled and locally configured |
| Wrong path or HTTP method | Explicit 404 or 405, not a fallthrough into model dispatch |

The application must check the authorization header before reading the review body. The HTTP request cap is 64 KiB, manuscript excerpt cap 12,000 characters, and context cap 2,000 characters; the body may contain only approved schema fields. For HTTP reviews, the caller cannot provide model URL, provider key, or destination. Response failures must not echo secrets, internal errors, or manuscripts.

After starting the server, run a **local, non-billable** liveness probe:

```bash
curl -i http://127.0.0.1:8765/healthz
```

It should return a JSON health response; `review_configured: true` means the configuration passed initial checks, **not** that the model is responsive or capable. An unauthorized synthetic POST must return a refusal, not a critique. A fully authorized, **synthetic non-sensitive** passage can be sent only after the local model is verified to be running. Check the returned schema, exact lens selection, source quotations, transport failures, and latency manually; if it cannot generate a valid response, leave inference disabled.

If using a browser, note that local browser extensions, other local software, the model runner itself, and system backups may access submitted text. Only submit writing that you own or may process. Inspect the model runner's logging and persistence settings; Aeonith cannot promise security for third-party software merely because traffic stays on loopback.

## Validation, troubleshooting and rollback

```bash
python3 -m unittest discover -s tests -v
python3 -m aeonith review --input examples/microfiction.json
```

The first command must pass before release. The second intentionally reports `provider_unavailable` without a selected provider; that is a healthy safety behavior. The tests use controlled fake providers and do not establish literary quality or a running model.

- If health says reviews are unconfigured, inspect the enable switch, token length, local endpoint syntax, and model label **without printing secrets**.
- If health is ready but requests fail, inspect only sanitized status and your local KoboldCpp availability. A configured model can still reject JSON mode, time out, or output invalid review JSON.
- To stop all new model dispatch, unset `AEONITH_ENABLE_LIVE_REVIEWS` (or set it to `false`) **and restart** the local service. You can also stop the server with `Ctrl+C`.
- If the service token is exposed, generate a new one and restart the local server. The old token is no longer valid after restart with a different environment.
- To roll back code, restore a reviewed source commit through ordinary Git version-control operations, then rerun tests and the synthetic local probes.

Do not equate a process that listens on a port with a safely hosted public service. A public Funnel deployment must pass its own external route/authentication and model qualification steps, and cannot rely on an earlier localhost test. Aeonith has no independently verified publicly accessible deployment, no original-GPT parity certificate, and no provider-independent assessment of literary insight. [Release criteria](RELEASE_GATES.md) distinguish source contracts, local function, public access, and literary quality.
