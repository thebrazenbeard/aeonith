# Aeonith private model-provider pilot — operator release gate

_v0.5.0 source candidate. No real model-backed deployment has passed this
checklist. A healthy web page and passing fake-provider tests do not qualify
actual inference._

## Intended first pilot

Use the existing Vercel project `aeonith`
(`prj_osJk28zPZLb4rfRbg7SPhK0sSA1o`) in the owner's **personal** scope.
The project has been read back with Vercel Authentication enabled for
`deploymentType: all`. Keep the audience to the owner only. The public browser
is not a free anonymous inference endpoint.

Recommended first backend: Vercel AI Gateway's OpenAI Responses-compatible
endpoint and its cataloged `openai/gpt-6-luna` model. This is an intended
selection, **not** a demonstrated real-model integration or promise of
availability/pricing in the owner's account. Hosted Functions use the
automatically provisioned `VERCEL_OIDC_TOKEN` for this exact Gateway URL, not
an ordinary API key; otherwise the project-specific Gateway budget would not
apply to the request.

Non-secret Vercel settings for a **protected preview**:

```text
AEONITH_PROVIDER_KIND=openai-responses
AEONITH_PROVIDER_URL=https://ai-gateway.vercel.sh/v1/responses
AEONITH_PROVIDER_MODEL=openai/gpt-6-luna
AEONITH_REQUIRE_VERCEL_GATEWAY_OIDC=true
AEONITH_STRUCTURED_OUTPUTS=true
AEONITH_MAX_LENSES=3
AEONITH_MAX_OUTPUT_TOKENS=4096
AEONITH_PROVIDER_TIMEOUT_SECONDS=45
AEONITH_DAILY_REVIEW_LIMIT=3
AEONITH_ENABLE_LIVE_REVIEWS=false
```

Required **server-side secrets**, to be created/configured by the owner in
Vercel settings, not pasted into chat, files, CLI arguments, logs, or browser
storage:

| Variable | Purpose |
| --- | --- |
| `AEONITH_SERVICE_TOKEN` | Separate strong 32+ character ASCII bearer token for author review calls; distinct in each environment |
| `AEONITH_ADMISSION_REDIS_URL` | The owner's durable Upstash Redis HTTPS REST endpoint (not an expiring example database) |
| `AEONITH_ADMISSION_REDIS_TOKEN` | The corresponding server-side Redis REST write token, never a read-only token |

For the hosted Gateway route do **not** set `AEONITH_PROVIDER_API_KEY` or
`AI_GATEWAY_API_KEY`. The deployed Vercel runtime supplies the OIDC credential.
The literal `AEONITH_REQUIRE_VERCEL_GATEWAY_OIDC=true` locks the pilot to the
exact Responses Gateway URL and its deployment OIDC token; a missing token,
alternative endpoint or adapter, or any configured Gateway/provider API key
fails closed even if Vercel runtime markers are missing. Invalid flag values
also fail closed. Never disable this lock to work around an authentication
failure or an unverified project budget.
For an alternative, explicitly approved provider, use its dedicated project
key and separate hard-enforced spend controls, and evaluate retention afresh.

Configure distinct preview and production Redis databases (or independently
isolated storage policies) so one environment cannot exhaust the other's
daily budget. Each review carries a lowercase UUIDv4
`X-Aeonith-Request-Id`. Redis executes one atomic Lua reservation, counts
one UTC-day invocation, and rejects a repeated ID for seven days. Failed and
timed-out model calls still consume an allowance; clients must not silently
retry with new IDs. Redis timeout, malformed reply, unavailable credentials,
and exhausted quota all deny model dispatch. This is an invocation limit, not
a financial ledger.

## External controls before first paid request

1. In the owner's Vercel AI Gateway **Budgets → Projects** settings, set an
   explicit **$1, non-resetting** budget for the **Aeonith project** and read
   it back. The official CLI equivalent is
   `vercel ai-gateway budgets set project aeonith --limit 1 --refresh-period none`.
   Vercel calls this a **soft cap**; a crossing request can overshoot it.
   The connected Vercel API does not currently expose this budget setting,
   and the cloud dashboard requires owner sign-in. Do not assume it exists.
2. Verify Gateway billing/credits, allowed model, processing and retention
   terms in the owner account. The Gateway's own prompt handling and the
   eventual model provider's retention policy are distinct. `store: false`
   in the Responses request does **not** establish zero retention.
3. Confirm Vercel Authentication remains `deploymentType: all`, and keep the
   service bearer token private. The service limits each HTTP body to 64 KiB,
   the manuscript to 12,000 characters, and the context to 2,000 characters.
   A shared bearer is **not** per-user identity; this pilot is single-owner.
4. Configure permanent Upstash credentials, review daily quota, and actual
   OIDC availability. No external service will be silently provisioned here.
5. Before turning `AEONITH_ENABLE_LIVE_REVIEWS=true`, verify that a reviewed
   preview deployment is running the exact planned commit and remains under
   the project budget. Environment-variable changes require a fresh deploy.

## Qualification sequence

1. Authorize a narrowly scoped **GitHub Actions Trusted Source** in Aeonith's
   Vercel **Settings → Deployment Protection → Trusted Sources**. Restrict it
   to GitHub account `thebrazenbeard`, repository `aeonith`, feature branch
   `feat/live-provider-pilot-20261101` and the **Preview** environment only.
   The test job needs GitHub `id-token: write`; obtain its short-lived token
   with `core.getIDToken()` and make it available only to the smoke step as a
   masked environment variable. Never print the token or follow redirects.
   The opt-in, non-billable six-probe smoke tool is:

   ```bash
   python -m scripts.preview_smoke --execute \
     --origin https://YOUR_VERIFIED_PREVIEW_HOST.vercel.app \
     --expected-host YOUR_VERIFIED_PREVIEW_HOST.vercel.app \
     --trusted-oidc-env GITHUB_OIDC_TOKEN
   ```

   Independently verify this full deployment origin and exact Git commit in
   Vercel metadata before invoking the test. The script cannot create an OIDC
   token, bypass protection, or run any network calls without `--execute`.
   Keep inference disabled for this test. On the protected preview, verify
   `GET /healthz` reports `status: ok` and
   the expected readiness flag. Route matrix: `GET /api/health` is health;
   `GET /api/review` and `POST /healthz` are 405; unknown paths are 404.
   Check both friendly and direct `/api?aeonith_route=review` POST aliases.
2. Check missing/invalid/duplicate bearer authorization is rejected **before
   reading a body or reserving quota**. Exercise malformed JSON, unsupported
   media type, excessive body, missing disclosure, missing request ID,
   duplicate ID (409), quota exhausted (429), Redis unavailable (503), and
   no echo of a secret or manuscript in error/logs. Rate rules must protect
   **all POST routes**, not just `/api/review`.
3. Only with the owner's explicit paid-inference permission and verified
   $1 Gateway budget, enable the switch in isolated preview and redeploy.
   Send **one** synthetic canary selecting three lenses:

   ```bash
   python -m scripts.live_canary --execute --allow-paid-inference \
     --url https://YOUR_VERIFIED_PREVIEW_URL/api/review \
     --expected-host YOUR_VERIFIED_PREVIEW_URL \
     --trusted-oidc-env GITHUB_OIDC_TOKEN \
     --lenses literary_thematic,stylistic,symbolic
   ```

   Independently verify the exact hostname against the selected Vercel
   deployment metadata before entering `--expected-host`. Remote requests
   fail before reading credentials if the host is missing or mismatched.
   The command reads the service token from `AEONITH_SERVICE_TOKEN` in its
   environment. The `--trusted-oidc-env` variable must be populated by the
   reviewed, protected GitHub Actions job, and the owner must authorize this
   separately paid synthetic call. The legacy `--vercel-bypass-env NAME` is
   an alternative only when the owner configured an appropriately scoped
   automation-bypass secret; never use both mechanisms in one request.
   Do not print or pass token values on command lines. This script emits
   aggregate structural counts and elapsed time, never the source passage or
   full critique.
4. Require HTTP 200, valid `aeonith.review.v1`, the exact selected lens set,
   source-exact quotations, synthesis, genuine provider provenance, and
   observed model identity/usage/cost from the Gateway dashboard. A single
   pass proves API interoperability, **not** literary quality.
5. Only then qualify a reviewed production deployment of the **same code**
   with independently configured production secrets and budget, repeat the
   synthetic check, review redacted logs and actual billing, and document a
   rollback candidate. Do not use a forced promotion to bypass failing
   Deployment Checks.

## Operational limitations

- Vercel Auth plus a bearer token restricts access but does not confer
  individual author identity, manuscript ownership, or third-party consent.
- The daily Redis allowance is cross-instance atomic but not a dollar-denominated
  reservation; provider billing can be greater than estimated and in-flight
  requests can complete beyond a Gateway soft cap.
- User-controlled writing is untrusted text, not an instruction source. The
  model has no tools, but its analysis remains a fallible interpretation.
- Human-blinded evaluation, original-GPT parity, and whole-book understanding
  are separate, **unpassed** gates.

Official platform references:

- [Vercel AI Gateway Python and OIDC](https://vercel.com/docs/ai-gateway/sdks-and-apis/python)
- [Vercel AI Gateway budgets](https://vercel.com/docs/ai-gateway/observability-and-spend/budgets)
- [Vercel AI Gateway pricing](https://vercel.com/docs/ai-gateway/pricing)
- [Upstash Redis REST command protocol](https://upstash.com/docs/redis/features/restapi)
- [Vercel Deployment Checks](https://vercel.com/docs/deployment-checks)
