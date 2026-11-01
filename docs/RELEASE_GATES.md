# Aeonith release and live-service qualification gates

_2026-11-01, v0.4.1 hosted-shell verification. This document distinguishes
working deployment health and browser rendering from pending authenticated
provider-backed review qualification._

The verified v0.3.0 source release was merged as [PR #6](https://github.com/thebrazenbeard/aeonith/pull/6)
at `8980df6989219ae026d958171b8fdaf200e7edfd`. It passed **226/226** local
Python 3.12 contract tests and the exact-head GitHub Actions Python 3.11,
3.12 and 3.13 matrix. Those checks did **not** exercise an HTTP service or an
external model. Earlier candidate text saying PR #6 was still pending was
historical and is retired.

The v0.4 protected HTTP/browser source release merged as
[PR #9](https://github.com/thebrazenbeard/aeonith/pull/9) at
`5ccfd7928b1c9587a9279d7d777b0ec31a6f7046`, with 272 local tests and
all three exact-head GitHub Actions jobs green. Vercel's first real build
reported `PYTHON_ENTRYPOINT_NOT_FOUND` because two handler candidates existed
without an explicit entrypoint. v0.4.1 selects `api.index:handler` and routes
health/review through a single dispatcher. The fix merged as
[PR #10](https://github.com/thebrazenbeard/aeonith/pull/10) at
`f90a64bc18a2d285638cbbe646d546ffb396a4f8`, with **275/275** local
tests, a built wheel, and three passing exact-head GitHub Actions jobs.

Vercel production deployment `dpl_DrkMtyBmkP9NP8iHFSGjLNr7akgC` for that
SHA reached **READY**. On 2026-11-01, the protected default production alias
[`aeonith-seven.vercel.app`](https://aeonith-seven.vercel.app/) loaded the
manuscript editor and `GET /healthz` returned
`{"schema_version":"aeonith.health.v1","service":"aeonith","status":"ok","review_configured":false}`.
An explicitly synthetic review with a noncredential test token produced a
provider-unavailable message and **no critique**. This is a successful
provider-disabled **web-shell** deployment, not qualified inference.

## Source and qualification state

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Reviewed source | A PR diff against exact `main` SHA, no private GPT configurations, knowledge assets or secrets in public Git | **v0.4 PR #9 and v0.4.1 PR #10 merged**; exact running SHA recorded |
| Local contracts | Full Python 3.11–3.13 test matrix and wheel smoke; static and live-service tests in CI | Local Python 3.12 **275/275 PASS**, wheel built; **3/3 exact-head GitHub Actions jobs passed** |
| HTTP boundary | Unauthorized requests never call providers; valid/invalid body, method, size, endpoint and error behavior exercised | Focused service/security/browser source tests passed; hosted synthetic no-provider denial observed; full deployed negative HTTP matrix still open |
| Browser interaction | Same-origin requests, no stored manuscript or credentials, safe rendering, accessible failure states | Browser UI visibly loaded; a noncredential synthetic review showed an explicit unavailable state; no live critique |
| Rate/cost control | Protection against unauthenticated abuse and concurrency, model spend and invocation limits enforced outside per-process memory | **Open production gate** |
| Privacy | Strict no-cache response policy, no manuscript/credential logging; explicit notice before external provider disclosure | Local source-tested; **full deployed headers/logs audit still open** |
| Provider availability | Missing credentials/provider reject honestly without fabricated criticism | Hosted health `review_configured: false` and synthetic unavailable response verified |
| Provider compatibility | A credentialed, cost-bounded call with an intentionally non-sensitive fixture, verified exact chosen model and backend | **Open; not proven by local provider fakes** |
| Deployment identity | Hosting project and scope verified; deployed SHA matches reviewed code; exact URL, HTTP status and logs captured | **READY** deployment `dpl_DrkMtyBmkP9NP8iHFSGjLNr7akgC`, source `f90a64bc…`, live `/healthz` and editor verified; runtime logs audit remains open |
| Staging and promotion | Protected preview and tested staging build before assigning a production domain; repeatable rollback | **Open; do not silently assume hosting defaults** |
| Post-deploy observability | Non-sensitive request/error logs and operational health, without manuscript bodies, prompt contents or credentials | **Open** |
| Knowledge rights | Explicit owner decision on license and rights for each GPT reference asset; no third-party knowledge imported by assumption | **Open** |
| Literary judgment | Blinded human comparisons, counter-readings and genre diversity, not a structural JSON pass or a second model score | **Open** |
| Ecosystem authority | Independently authenticated, host-owned bindings and consent if later wired into Rezon/CCB | **Open; prototype is not production host authorization** |

## Minimum live-service pass criteria

1. On a review request, validate caller authentication **before** reading,
   echoing, logging or dispatching manuscript text. A rejected request must
   never reach the model provider.
2. Reject unsupported methods, media types, malformed JSON and oversized
   bodies with bounded responses. Do not expose internal exceptions, secret
   values, endpoint configuration or provider payloads in failures.
3. When a language-model provider is absent, return an explicit unavailable
   state; serving a healthy web page must not be presented as model inference.
4. Enforce upstream spending/rate controls and make the provider destination
   and disclosure policy host-owned. A caller's `consent`, `lease` or
   `provider` string is not an authorization grant.
5. Verify a protected preview with benign GET and negative POST probes,
   then a reviewed production build with the **same code** before promotion.
   Record the exact repository SHA and running URL. Test rollback readiness.
6. Only after an authorized, budgeted, non-sensitive model request can the
   selected live model be described as interoperable. Literary quality and
   original GPT parity remain separate human-review questions.

## Hostile release challenges

> A publicly reachable `200 OK` health check proves a deployment responds;
> it does not prove authentication, model availability, manuscript privacy,
> meaningful criticism or acceptable cost exposure.

> A bearer token checked in the application does not, by itself, enforce a
> durable per-user model budget. Serverless instances can run concurrently;
> in-memory counters are not an authoritative global spend ledger.

> A valid exact manuscript quotation validates substring presence, not
> historical truth, authorial intent or a nuanced literary interpretation.

> Automated schema checks and model agreement are not an independent
> human literary assessment. Keep such evaluation separate from uptime.

## Current decision

The protected, provider-disabled **web shell is deployed**. Continue
qualifying the review service. **Do not publish an
unprotected paid-inference endpoint** or claim a full live critic until the
authentication, provider, spend, privacy and runtime gates above are
actually exercised. Source-only status and a protected, no-provider
preview may be reported distinctly, if that is all the deployed environment
can currently demonstrate.

