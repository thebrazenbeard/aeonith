# Local model qualification — paid provider canary retired

**The former paid-provider canary and protected-cloud qualification process are retired.** The hard additional-spending authorization is **$0.00**, with no cloud service, hosted model, metered request, provider credential, or billing budget. Do not run an old `scripts.live_canary` or Vercel preview-smoke command from archived commits or draft pull requests. This file remains at the old path so historical references do not become dead links.

Aeonith can request a genuine critique through an already-running local model on an existing machine, but **has not thereby proven a model's quality or even a particular machine's compatibility**. Source fixtures and fake-provider contracts establish software behavior, not actual literary judgment.

## Qualify an existing local model

1. Select a model and runner already installed and permitted for local use. For example, [KoboldCpp](https://github.com/LostRuins/koboldcpp) offers an OpenAI-compatible Chat Completions API at `http://127.0.0.1:5001/v1/chat/completions` by default. No download, external endpoint, stored API key, or tunnel is required by Aeonith.
2. Keep the model runner and Aeonith bound to **loopback**, not a public listener. Inspect the local model runner's logging and persistence settings. Use only synthetic, non-sensitive writing for qualification.
3. Configure `AEONITH_PROVIDER_KIND=local-openai-compatible`, the literal loopback endpoint, a locally accepted model label, a freshly generated service token, and `AEONITH_ENABLE_LIVE_REVIEWS=true`; follow the exact [local runbook](SERVICE_DEPLOYMENT.md).
4. First check `/healthz` and negative HTTP cases (unauthorized POST, invalid JSON, wrong method, oversized body). A healthy response or `review_configured: true` **does not** prove the local model works.
5. Submit one harmless short passage with a small selected lens set. Require an actual complete `aeonith.review.v1` response, correct lens set, nonempty analyses, grounded exact quotations for textual claims, synthesis, and no undisclosed tools or network destinations. If the model stalls, rejects structured JSON, or returns invalid output, mark the local-model gate as **failed** or **partial**; do not silently switch to a remote backend.
6. Separately assess literary usefulness through blinded human review across genres, calibration, counterreadings and repeated samples. JSON conformance is necessary but insufficient.

The model runner may use CPU/GPU memory and take time; those resource demands do not authorize spending on a new service. Never log or publish bearer secrets, full private manuscripts, or full model responses. Retain only sanitized, user-consented qualification notes.

## What a pass does not establish

- Equivalence to the original custom GPT, including private knowledge attachments or special activation behavior.
- The truth of historical references, author intent, literary insights or any external citation.
- Compatibility with other GGUF models, different runtime versions or larger contexts.
- Safe multi-user/public serving. The supported HTTP listener is private loopback; it is not a cloud deployment.
- Guaranteed text confidentiality from browser extensions, other local processes, model logs, or backups.

The [release gate matrix](RELEASE_GATES.md) distinguishes confirmed source checks, observed local operation, and still-unverified literary capabilities. Historical paid-pilot context is retained as an explicit cancellation notice in [LIVE_PROVIDER_PILOT.md](LIVE_PROVIDER_PILOT.md).
