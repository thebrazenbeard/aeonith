# Aeonith HTTP service: protected deployment runbook

This describes the intended Vercel deployment of Aeonith's independently
implemented literary critic. Source checks and a functioning HTTP endpoint
are **not** proof of original-GPT parity, model suitability, safe retention
by an external model provider, or end-to-end literary quality.

## Route and packaging contract

The Python Vercel Functions runtime (currently beta) supports the standard
library `BaseHTTPRequestHandler` entry point in `api/*.py`. The repository
uses the root `pyproject.toml` (Python 3.11+) and includes no mandatory
third-party runtime dependency. Vercel currently supports Python 3.12 by
default; its deployed Python version must be verified from the build.

| Public route | Function | Purpose |
| --- | --- | --- |
| `/` | `public/index.html` | Same-origin client UI; no embedded secrets |
| `/healthz` | `api/health.py` | Process/packaging health; never a model-quality or provider-availability attestation |
| `/v1/critique` | `api/review.py` | Authorized, bounded JSON review request |

The direct `/api/health` and `/api/review` function URLs also exist;
the same handler-level protections must apply there. `vercel.json` rewrites
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

Use the confirmed owner team `team_4yKVQ8CAcswaelgyQBineyrx`
(`patrickallynsims-7966s-projects`). No Aeonith project existed in that
team at the time this runbook was written. Resolve the target team and
project again before any creation or deployment.

For the **first project creation**, set Vercel Authentication to
`ssoProtection: { "deploymentType": "all" }` atomically with the
GitHub repository connection. Do not rely on a presumed team default or
auto-publish an unprotected preview. Read back the project to verify
All-Deployments protection before allowing an inference endpoint to run.
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
| `AEONITH_PROVIDER_API_KEY` | Provider credential with minimum scope and a hard spend limit when available |
| `AEONITH_STRUCTURED_OUTPUTS` | Optional literal `true` to request strict JSON Schema from a provider that supports it; independently validated afterward |

The request must contain a valid `Authorization: Bearer <service token>`
before any manuscript parsing or inference. If using an external provider,
the caller must explicitly acknowledge disclosure via
`X-Aeonith-Disclosure: accepted`. This is a request assertion, not
authenticated owner authorization or proof of the author's consent.
Models, provider URLs, API keys and token ceilings are **not** request
parameters. CORS is not opened for other origins.

Start with `AEONITH_ENABLE_LIVE_REVIEWS` unset or `false` and no provider
key. A deployed health endpoint can be live while review attempts fail
closed. **Do not call this a working live critique service until a
credentials-configured, authorized end-to-end provider call passes.**

## Release and evidence gates

1. Inspect the exact GitHub head, CI test and wheel jobs, changed files,
   release scope and secrets exposure; do not promote a moved head.
2. Create/link the Vercel project in the resolved team with All-Deployments
   Vercel Authentication already enabled. Keep deployment preview/protected.
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
