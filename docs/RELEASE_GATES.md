# Aeonith zero-cost release and qualification gates

**Hard invariant:** additional spending authorization is **$0.00**. This excludes paid inference APIs, cloud platforms, metered serverless deployments, hosted databases, paid tunnels, paid quotas, and providers that could bill later. A nominal minimum $1 budget, free trial that can convert into charges, or a soft spending cap does **not** satisfy the invariant. Do not create resources, test paid services, or reuse unrelated saved credentials. There is no active Vercel deployment to maintain.

The repository can be released as a source package and run on an already-owned machine without external infrastructure. A real live local critic requires that a suitable model and runner already be available. A provider-disabled UI is a **shell**, not completed inference; model-backed quality must be separately tested.

## Evidence ledger

| Gate | Required evidence | Result classification |
| --- | --- | --- |
| Source integrity | Exact source SHA, reviewed diff, no Vercel/cloud deployment config, no embedded model credentials or private GPT material | Record **confirmed** only after exact-head review |
| Zero-cost safety | Local-only server/provider config, no paid fallback, no mandatory Redis/OIDC/API key, and no automatic billed integration in CI | Confirm with negative config tests; nominal budgets are insufficient |
| Python contracts | Fresh complete stdlib unit/integration suite on the candidate checkout; GitHub workflow matrix if it can run at $0 under the owner's account | Green prior commits do not certify new changes |
| Installability | Wheel/build/import/CLI smoke from the reviewed source without required paid downloads | Record platform and command results |
| Loopback default | Web UI and API on `127.0.0.1`; no accidental public listener | Verify actual bound address at runtime |
| HTTP boundary | Auth before body read; invalid methods, JSON, content types, body sizes, and unconfigured provider fail safely | Verify with real localhost HTTP requests, not only mocks |
| Manuscript privacy | No body/secret echo on errors; browser does not persist manuscript/token; local logs inspected | Privacy beyond the app (browser extensions/model runner) remains separate |
| Local provider protocol | Explicit local URL, no paid destination or proxy, no credentials, no redirects, bounded time and output | Verify with fake local endpoint and, optionally, an already-owned runner |
| Genuine model operation | One owner-approved harmless passage through the already-running local model, valid complete result and exact selected lens set | **Unverified** until observed on the owner's machine |
| Literary quality | Blinded human assessment across texts, counterreadings, sensitivity to evidence, stability over multiple runs | Distinct from schema and health checks |
| Original-GPT parity | Documented behavior comparison and rights-cleared source references, not inferred from branding | **Unverified** until tested independently |
| Ecosystem access | Separate authentication/owner consent for any future integration, with no unapproved write authority | Host adapter prototype is not a production guard |

Status labels are **confirmed**, **partial**, **unverified**, and **failed**. A green source test cannot be promoted to a confirmed deployment or model-quality claim. The old hosted web-shell smoke tests remain historical evidence only, not an available service or a release requirement.

## Minimum local release sequence

1. Review the exact repository diff and source commit. Remove stale deployment targets, secrets, paid-provider defaults and dangling hosted-service links. Leave actual cloud account state outside this repo.
2. Run `python3 -m unittest discover -s tests -v` and build/import checks on the resulting source. Resolve regressions before merge.
3. Run `python3 -m aeonith.local_server` with model dispatch disabled; confirm GET health, UI asset serving, unsupported methods, unauthorized POST and oversized-body denial **against localhost**. Never claim model readiness from this shell test.
4. Optionally, with a capable model **already installed and running locally**, set the strict `local-openai-compatible` adapter and send a harmless, explicitly authorized sample. Evaluate actual JSON shape, quote grounding, selected lens identity, error handling, performance and resource usage. If no local model is accessible, mark that gate **unverified**, not failed or passed.
5. Conduct human literary evaluation separately from structural validation. Keep private manuscripts and full critiques out of public logs and CI artifacts.
6. Merge only the exact reviewed, passing source. Record the commit and test commands. No paid or publicly accessible deployment is part of this release path.

## Hostile checks

> `200 OK` on `/healthz` proves that a process responded, not that a model is available, the critique is good, or data retention is safe.

> An unauthenticated refusal is necessary but insufficient for exposing the listener to untrusted networks. The supported deployment is private loopback.

> Matching a submitted quote is evidence of string presence, not proof of the interpretation, historical claim, causal reasoning, or authorial intent.

> A selected model name, an API-compatible endpoint, or a model's own statement that it complied does not prove the strict review schema was met.

> A $1 spending cap, cloud promotional credit, or a rate limiter cannot turn a metered paid service into a hard $0 deployment.

See the [local deployment runbook](SERVICE_DEPLOYMENT.md), [offline evaluation](../evaluation/README.md), and [retired paid-pilot note](LIVE_PROVIDER_PILOT.md).
