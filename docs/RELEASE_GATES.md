# Aeonith release and live-service qualification gates

_2026-10-31, v0.4 live-service candidate. This document distinguishes merged
v0.3 source evidence from pending v0.4 API, deployment and model qualification.
It is not a deployment receipt._

The verified v0.3.0 source release was merged as [PR #6](https://github.com/thebrazenbeard/aeonith/pull/6)
at `8980df6989219ae026d958171b8fdaf200e7edfd`. It passed **226/226** local
Python 3.12 contract tests and the exact-head GitHub Actions Python 3.11,
3.12 and 3.13 matrix. Those checks did **not** exercise an HTTP service or an
external model. Earlier candidate text saying PR #6 was still pending was
historical and is retired.

## Source and qualification state

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Reviewed source | A PR diff against exact `main` SHA, no private GPT configurations, knowledge assets or secrets in public Git | **Pending v0.4 PR**; v0.3 source was merged |
| Local contracts | Full Python 3.11–3.13 test matrix and wheel smoke; static and live-service tests in CI | Candidate local Python 3.12 **272/272 PASS**; **pending exact-head GitHub v0.4 CI** |
| HTTP boundary | Unauthorized requests never call providers; valid/invalid body, method, size, endpoint and error behavior exercised | **32/32 focused service/security/browser source tests passed**; deployed HTTP pending |
| Browser interaction | Same-origin requests, no stored manuscript or credentials, safe rendering, accessible failure states | Static contract tests passed; **actual deployed browser behavior pending** |
| Rate/cost control | Protection against unauthenticated abuse and concurrency, model spend and invocation limits enforced outside per-process memory | **Open production gate** |
| Privacy | Strict no-cache response policy, no manuscript/credential logging; explicit notice before external provider disclosure | **Pending live proof** |
| Provider availability | Missing credentials/provider reject honestly without fabricated criticism | **Pending hosted proof** |
| Provider compatibility | A credentialed, cost-bounded call with an intentionally non-sensitive fixture, verified exact chosen model and backend | **Open; not proven by local provider fakes** |
| Deployment identity | Hosting project and team verified; deployed SHA matches reviewed code; exact URL, HTTP status and logs captured | **No confirmed deployment receipt yet** |
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

Prepare and qualify the live-service candidate. **Do not publish an
unprotected paid-inference endpoint** or claim a full live critic until the
authentication, provider, spend, privacy and runtime gates above are
actually exercised. Source-only status and a protected, no-provider
preview may be reported distinctly, if that is all the deployed environment
can currently demonstrate.

