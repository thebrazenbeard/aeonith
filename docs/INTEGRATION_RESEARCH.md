# Aeonith ecosystem integration: bounded v1 proposal

Date: 2026-10-31. Evidence: live public GitHub source reads at the exact `main`
commit SHAs below. The existing Aeonith GPT's private instructions and knowledge
were not presumed available. This report does **not** claim a deployed runtime.

## Minimum useful seam

`capability_adapter.py` wraps the source package's `aeonith.core.critique` as a
single JSON request/response transaction. It makes no network connection,
persists no state, and invokes no host effects itself. The caller may inject a
model provider via core; that provider may disclose text externally, so consent,
privacy, provider endpoint, authentication, quotas, and execution authority stay
with the invoking host. Envelope `request_id` correlates responses only; it is
not a lease, identity proof, replay-protection mechanism, or permission token.

The input and output envelopes have standalone Draft 2020-12 schema files.
Invocation envelope:

```json
{
  "kind": "capability.invoke.v1",
  "request_id": "caller-generated-001",
  "capability": "aeonith.review.v1",
  "payload": {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Draft", "text": "The paragraph to critique."},
    "lenses": ["stylistic", "narrative_structure"]
  }
}
```

The response is `capability.result.v1` with the same request ID and an `outcome`
of `ok`, `rejected`, `unavailable`, or `failed`. `result` contains the core's
typed critique **only on validated completion**; it is `null` for all
non-completed statuses and adapter errors. An optional top-level `core_status`
retains the recognized core failure state without forwarding arbitrary
untrusted failure metadata. An unavailable semantic review is never promoted
into a completed critique.

The adapter rejects extra envelope keys, wrong capabilities, malformed and
duplicate-key JSON, non-finite numbers, and inputs over 256 KiB. The adapter
also caps its serialized result at 2 MiB; a host must additionally bound
downstream output, model cost and resource usage. No process supervision, tenant
isolation, replay persistence, provider attestation, or authentication exists
in this adapter; none should be inferred from the JSON contract.

## Owner ecosystem roles (source observations)

| Source (commit) | Observed contract | Appropriate Aeonith relation |
| --- | --- | --- |
| [Rezon](https://github.com/thebrazenbeard/rezon) `cdd36d0df2a6194dd2738fb29ee8931933bcef7b` | [Reasoning node V0](https://github.com/thebrazenbeard/rezon/blob/main/docs/contracts/REASONING_NODE_V0.md) describes typed input/output, falsifier, verification and evidence reference boundaries; its README says collective workers require explicit operator provision and do not attest model identity. Proprietary/source-visible license. | Optional `EXTERNAL_TOOL` or `LLM` specialist, consuming the JSON result as **candidate review**, not proof or autonomous quorum. No source copy. |
| [CCB Base](https://github.com/thebrazenbeard/ccb-core) `57b5bb97b923e43da0fb677b4e4a907bab222e37` | Canonical transport/runtime code; protected runtime trust anchors and deployment overlay external to public source. Proprietary/source-visible license. | A future host may route a **separately authorized** critique request/receipt. The adapter is not a Bus writer, actor, admission source, or runtime installation. |
| [Chat Communication Bus](https://github.com/thebrazenbeard/chat-communication-bus) | Public legacy coordination and source, expressly **not** a confidential mailbox or live runtime proof. | Never submit private manuscript text to a public issue or PR as an integration shortcut. |
| [unbound-sol](https://github.com/thebrazenbeard/unbound-sol) `1749586848429f845ace22b2b0fa84d9e7a0ddf0` | Public-safe state and connections; `PUBLIC_BOUNDARY.md` prohibits private transcripts and personal records. Proprietary/source-visible license. | Optional public-safe, source-pinned architecture documentation only; do not persist raw critiques or manuscripts without owner approval. |

## External libraries and research considered

| Candidate (GitHub `main` SHA; license) | Benefit | Risk / v1 disposition |
| --- | --- | --- |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) `d7845c073a2b9ba5ab2817ecf93d3e45ef24cd14`; MIT | Standardized tool exposure over stdio or HTTP. | **Later opt-in**. Host policy, credential handling, network exposure and actual MCP contract qualification must be added. No MCP dependency in core. |
| [Promptfoo](https://github.com/promptfoo/promptfoo) `5582f347bbc5359b201ce2d48c9c7fbebd8dcbd9`; MIT | Declarative prompt/eval matrices, model comparisons, red-teaming and CI. | **Later eval tool**, not production dependency; requires npm/runtime and may send fixtures to configured providers. Start with local deterministic contract and human-rated writing fixtures. |
| [DeepEval](https://github.com/confident-ai/deepeval) `90e230cbe916c73240a48312c494065a39bf52d1`; Apache-2.0 | LLM-as-judge evaluation of application quality and traces. | **Research/eval only**, not ground truth for subjective literary quality; model bias, inference cost, privacy. |
| [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python) `3462000f323b4f3d03c10d09b9d82c03119f2c59`; Apache-2.0 | Trace IDs, latency and errors across hosts. | **Later opt-in** with strict manuscript/prompt redaction, configurable exporter and host-owned retention. No default external telemetry. |
| [LangGraph](https://github.com/langchain-ai/langgraph) `e5c961d7fbe7ca6fdd4c94c84d90511372514d55`; MIT | Durable multi-step agent orchestration. | **Not needed for thin v1**. Adds mutable state, persistence and orchestration complexity before critique accuracy is qualified. |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) `47b8c364cf6b4eceafbd284780d9d2b457a3762e`; MIT | Typed model/agent output and provider compatibility. | **Possible optional adapter** after stable core schema. Avoid forcing a dependency to claim provider-agnosticism. |

No code was copied from these sources. License metadata was read live from GitHub;
individual-file third-party licensing was not audited. The owner repositories are
source-visible/proprietary, so integration should be contract-level.

### Research cautions

- [Self-Refine (Madaan et al., 2023)](https://arxiv.org/abs/2303.17651) evaluates iterative feedback and revision across several tasks; it supports an **optional** author-controlled critique/revision loop, not an automatic rewrite accepted as superior.
- [Judging the Judges (Shi et al., 2024)](https://arxiv.org/abs/2406.07791) reports position bias in pairwise LLM evaluation; shuffle/blind candidate order in comparative tests.
- [Can Language Models Evaluate Human Written Text? (2024)](https://arxiv.org/abs/2407.17022) studies 100 student essays and finds human-assessed judgement validity varies sharply by genre, weaker on subjective works. This small sample cautions against objective literary scores. Do not generalize its percentages to all authors, languages, or models.

## Explicit nonclaims and next acceptance gates

1. This interface does not recover the GPT's hidden system instructions or knowledge files.
2. Source-test pass is not a live provider qualification or actual CCB/Rezon integration.
3. Provide at least one host-approved provider and run end-to-end critique tests on held-out writing with an independent human review rubric; record provider/model/version and privacy terms.
4. For a future CCB or MCP exposure, add host-owned consent, replay controls, tenant separation, text-size and output-size budgets, rate limits, redaction, and effect audit before enabling any route.
5. Preserve source/review/installation/runtime evidence as separate classes; no automatic model output may authorize changes to the author’s manuscript or downstream state.
