# Retired: paid cloud-provider pilot

**Status: cancelled. Do not execute or re-enable.**

An earlier unmerged v0.5 candidate explored a protected Vercel AI Gateway / Redis-backed paid-inference pilot. It was not qualified with a real model call, and its proposed minimum $1 project budget violated the owner's hard **$0.00 additional spending** limit. The owner requested deletion of the Vercel account; historical deployment READY states and preview URLs must not be presented as a currently available service.

The retired design is **not** an approved backup, fallback, optional deployment instruction, or route for circumventing the spending limit. This file intentionally contains no provisioning commands, OIDC instructions, credentials, model-call canary, or instructions to use Vercel, Upstash, or paid model APIs. Do not infer permission to spend from old draft PRs, stored keys, tunnels, or the fact that a vendor offers promotional credits.

## Supported replacement

Use the local-only design documented in [SERVICE_DEPLOYMENT.md](SERVICE_DEPLOYMENT.md): Python standard-library HTTP service bound to `127.0.0.1`, a strong bearer token, and an explicitly selected local OpenAI-compatible model runner on existing hardware. Without a local model, leave the review switch disabled and report `provider_unavailable` honestly.

Source tests can check safety boundaries without ever connecting to a paid service. A harmless test using a **previously installed** local model is optional and must not initiate new spending. Validate actual output structure and literary usefulness separately; neither a local HTTP health check nor a fake-provider unit test proves real AI criticism.

See [RELEASE_GATES.md](RELEASE_GATES.md) for the no-cost release checklist and evidence classifications.
