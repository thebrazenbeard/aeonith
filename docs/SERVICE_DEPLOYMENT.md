# Aeonith HTTP service: protected deployment runbook

This describes the Vercel deployment of Aeonith's independently
implemented literary critic. Source checks and a functioning HTTP endpoint
are **not** proof of original-GPT parity, model suitability, safe retention
by an external model provider, or end-to-end literary quality.

**Verified 2026-11-01 (UTC):** The protected, provider-disabled web shell is
running at [aeonith-seven.vercel.app](https://aeonith-seven.vercel.app/).
Vercel reports deployment `dpl_DrkMtyBmkP9NP8iHFSGjLNr7akgC` as `READY`
for GitHub commit `f90a64bc18a2d285638cbbe646d546ffb396a4f8`.
Before authentication was extended to all deployments, the live browser editor
loaded, and `/healthz` returned `status: ok` with
`review_configured: false`. A synthetic, unauthorized review reported
provider unavailable. No real model request or model-quality qualification
has taken place. The Vercel connector's private-deployment probe returned
a permission error; the earlier browser verification succeeded. After Vercel
Authentication changed to **All Deployments**, the v0.5.0 candidate preview
`dpl_7V4riYoo2y53Hww5Mk53fzvo6JgV` reached **READY** for source commit
`95d130a9b3740658019fc5cee562e0bfb33e256e`, with passing exact-head
CI. However, its protected HTTP smoke is **blocked**: the browser requires
login and the connector's protected-deployment fetch returned 403. Do not
represent READY as proof that the runtime rewrite routes are functional.

## Route and packaging contract

The Python Vercel Functions runtime (currently beta) supports the standard
library `BaseHTTPRequestHandler` entry point. The Vercel project expects a
**single** application entrypoint, selected in `pyproject.toml` as
`[tool.vercel] entrypoint = "api.index:handler"`. That dispatcher delegates
GET liveness to `api/health.py` and authenticated POST reviews to
`api/review.py`. The repository
uses the root `pyproject.toml` (Python 3.11+) and includes no mandatory
third-party runtime dependency. Vercel currently supports Python 3.12 by
default; its deployed Python version must be verified from the build.

| Public route | Function | Purpose |
| --- | --- | --- |
| `/` | `public/index.html` | Same-origin client UI; no embedded secrets |
| `/healthz` | `api/index.py` → health handler | Process/packaging health; never a model-quality or provider-availability attestation |
| `/v1/critique` | `api/index.py` → review handler | Authorized, bounded JSON review request |

The direct `/api/health` and `/api/review` URLs also exist as rewrites to
`/api`, and the same handler-level protections apply. `vercel.json` rewrites
the friendly routes above and applies restrictive same-origin CSP, frame
blocking and no-store headers. The UI must use separately served scripts
and CSS, not inline JavaScript, to satisfy that CSP.

Vercel's function payload ceiling is 4.5 MB; Aeonith intentionally imposes
a smaller application input budget. Do not raise it to accommodate entire
books: the long-form source planner works by bounded excerpts, and neither
the HTTP service nor its current model adapters provide whole-book
synthesis. The Vercel function timeout is capped at 60 seconds here, so
model transport timeouts must be shorter and genuine long-running work
requires a separate, explicitly reviewed asynchronous architecture.

## Protection and credentials

Resolve the account scope and project ID before any deployment. A previous
team-scoped creation attempt returned HTTP 403, while the user subsequently
created an `aeonith` project in the accessible personal scope. Do not create
a duplicate project or silently switch between scopes.

For any **new project creation**, set Vercel Authentication to
`ssoProtection: { "deploymentType": "all" }` atomically with the
GitHub repository connection. Do not rely on a presumed team default or
auto-publish an unprotected preview. Read back the project to verify
All-Deployments protection before allowing an inference endpoint to run.
An existing project's `all_except_custom_domains` setting protects ordinary
deployment URLs but is not sufficient to assert protection on future custom
domains. **Aeonith's project has since been updated and read back with
`ssoProtection.deploymentType=all`.** Keep it there for the private pilot.
Vercel's September 2026 update makes this protection available on every
plan; verify current terms and settings in the owner account.

Configure the following as private, server-side Vercel environment variables
for the intended environment; none belongs in `public/*`, a repository
commit, browser storage, build logs or client JavaScript:

| Variable | Meaning |
| --- | --- |
| `AEONITH_SERVICE_TOKEN` | Independently generated high-entropy bearer token required by the service; use distinct values across environments |
| `AEONITH_ENABLE_LIVE_REVIEWS` | Literal `true` is the deliberate inference-enable switch; otherwise deny model calls |
| `AEONITH_PROVIDER_KIND` | Chosen compatible adapter, default `openai-responses` |
| `AEONITH_PROVIDER_URL` | Fixed, trusted HTTPS inference endpoint, set by operator, never a caller-controlled URL |
| `AEONITH_PROVIDER_MODEL` | Explicitly selected provider-compatible model |
| `AEONITH_PROVIDER_API_KEY` | Credential for an ordinary, explicitly chosen provider; hosted Vercel AI Gateway requires OIDC instead |
| `AEONITH_STRUCTURED_OUTPUTS` | Optional literal `true` to request strict JSON Schema from a provider that supports it; independently validated afterward |
| `AEONITH_ADMISSION_REDIS_URL` / `AEONITH_ADMISSION_REDIS_TOKEN` | Permanent Upstash Redis REST admission ledger and server-side write token; fail-closed when absent |
| `AEONITH_DAILY_REVIEW_LIMIT` | Atomic global per-UTC-day invocation allowance, 1–1000; separate by environment |
| `AEONITH_MAX_LENSES` | Optional bounded lens count (1–14; default 14) |
| `AEONITH_MAX_OUTPUT_TOKENS` | Optional bounded output ceiling (256–8192; default 4096) |
| `AEONITH_PROVIDER_TIMEOUT_SECONDS` | Optional bounded model timeout (1–50; default 45) |

The request must contain a valid `Authorization: Bearer <service token>`
before any manuscript parsing or inference. If using an external provider,
the caller must explicitly acknowledge disclosure via
`X-Aeonith-Disclosure: accepted`. This is a request assertion, not
authenticated owner authorization or proof of the author's consent.
Models, provider URLs, API keys and token ceilings are **not** request
parameters. CORS is not opened for other origins.

For the intended first Vercel AI Gateway pilot, set the exact provider URL
`https://ai-gateway.vercel.sh/v1/responses` and namespaced model
`openai/gpt-6-luna`. The Vercel worker uses its injected `VERCEL_OIDC_TOKEN`
for that exact route, **not** an ordinary Gateway/API key that would bypass
the Gateway **project** budget. Do not enable paid reviews until a $1
non-resetting project budget is saved and read back in the owner dashboard;
it is a soft cap with possible in-flight overrun. Upstash admission must also
be configured, and its remote success is required before provider dispatch.
See the [private model-pilot release checklist](LIVE_PROVIDER_PILOT.md).

Start with `AEONITH_ENABLE_LIVE_REVIEWS` unset or `false` and no provider
key. A deployed health endpoint can be live while review attempts fail
closed. **Do not call this a working live critique service until a
credentials-configured, authorized end-to-end provider call passes.**

## Release and evidence gates

1. Inspect the exact GitHub head, CI test and wheel jobs, changed files,
   release scope and secrets exposure; do not promote a moved head.
2. Create/link the Vercel project in its verified account scope with
   All-Deployments Vercel Authentication already enabled for new projects.
   The existing personal-scope project's mode was tightened and read back as
   `all`; retain this setting for all domains. Keep previews protected.
3. Verify the project Git source SHA and settings, the deployed
   `/healthz` route, and 405/4xx responses for unsupported methods,
   unauthorized requests, malformed JSON, missing disclosure and oversized
   bodies. Test that no manuscript or credential is echoed in errors.
4. Configure a limited provider account only after privacy/cost approval.
   Turn on the live review switch and run a consented, synthetic
   provider-backed critique. Validate actual output schema and evidence
   references, latency, errors, billing and provider retention terms.
5. Only then promote the **same tested build** to production. Record its
   URL, deployment ID, source SHA, protection mode, model ID, exact tests,
   observability and rollback candidate. Keep protection in place unless
   public serving and abuse controls are deliberately authorized.

Changing a Vercel project's production branch or connecting Git may trigger
new deployments. Neither a source merge nor a readiness label substitutes
for this post-deploy probe.

## Privacy, abuse and rollback

- Treat manuscripts, model-generated analysis, source hashes and bearer
  tokens as sensitive. Do not log request/response bodies or secrets.
- Serverless in-process counters are not a reliable cross-instance rate
  limiter. A bearer token and Vercel Authentication reduce exposure but
  are **not** per-user quotas or a financial circuit breaker. Before
  opening access to multiple users, add durable rate/cost limits and
  provider spend caps.
- Keep external-model retention, geographic processing and cost settings
  under explicit operator review. The application cannot guarantee them.
- In an incident, disable `AEONITH_ENABLE_LIVE_REVIEWS`, revoke exposed
  service and provider credentials, inspect sanitized logs and Vercel
  usage, and use Vercel's deployment rollback/promote controls to restore
  a known-good deployment. Verify actual behavior after rollback; merely
  changing an environment setting may require a redeployment.

Official platform sources:

- [Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Function limits](https://vercel.com/docs/functions/limitations)
- [Static configuration and rewrites](https://vercel.com/docs/project-configuration/vercel-json)
- [Deployment protection](https://vercel.com/docs/deployment-protection)
- [All-deployments authentication update](https://vercel.com/changelog/protect-production-deployments-for-free-on-every-plan)
- [Deployments and rollback](https://vercel.com/docs/deployments)
