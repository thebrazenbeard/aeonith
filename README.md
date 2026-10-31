# Aeonith

Aeonith is a **model-assisted literary criticism engine** reconstructed from the observable behavior and owner-accessible configuration of [Aeonith, the Transcendent Critic](https://chatgpt.com/g/g-67f64b3b94348191b6f6ee4a83135b5a-aeonith-the-transcendent-critic), a custom ChatGPT GPT.

This repository is an **independently implemented, testable starting point**—not an export of the GPT, its model weights, hidden activation material, or private reference files. It critiques user-supplied written works with fourteen critical perspectives and an overarching synthesis when an explicitly configured language-model provider is available.

## What works

- A Python 3.11+ standard-library package, JSON review CLI, single-command manuscript workflow, UTF-8 input converter, and readable Markdown report renderer.
- Fourteen separately identified critical lenses: psychological, literary/thematic, narrative structure, character development, historical/cultural, philosophical, genre-specific, stylistic, sociological, moral/ethical, symbolic, reader-response, linguistic, and comparative.
- A synthesis field, concrete passage references, uncertainty/limitations, and an optional set of challenges.
- Explicitly selected HTTP adapters for compatible Chat Completions and OpenAI-style Responses endpoints. Chat retains legacy defaults plus opt-in model-specific token/temperature settings. Responses uses `max_output_tokens` and separated instructions. Both can request strict JSON Schema output when supported. **No real model/provider interoperability is claimed without a live qualification run.**
- Fourteen distinct, evidence-oriented critical-method prompts that ask for competing readings and calibrated uncertainty; the actual quality of model interpretations remains unverified.
- Validation that quoted passages occur in the submitted text and supplied evidence-reference IDs exist. **A matching quotation does not prove the interpretation is correct.**
- Optional exact-quote location sidecar with Unicode character offsets, repeated-occurrence ambiguity, and manuscript fingerprints.
- A deterministic chapter/excerpt planner for longer writing, with source-complete offsets; no automatic whole-book synthesis.
- An offline quality-audit and blinded human-comparison harness with display-bound annotations and descriptive aggregation. Its checks are **not** evidence of literary insight.
- Explicit error states when no provider is configured, a request is invalid, the provider fails, or the provider returns an invalid structure. No review is fabricated on those paths.
- A bounded, read-only JSON invocation adapter for future ecosystem integration. This adapter does not supply host authorization or a deployed service.
- The standalone `capability_adapter.py` stdin/stdout entrypoint has no model configuration and deliberately returns `provider_unavailable`; a host must inject an explicitly configured reviewer to obtain a real critique.

The tests verify these contracts with local fixtures and controlled providers. **Literary quality, original-GPT parity, live-provider compatibility, and deployment have not been established by those tests.**

## Try the CLI

For a plain UTF-8 manuscript, the shortest local path is:

```bash
python3 -m aeonith.workflow --input draft.md --title "Draft"
```

This deliberately returns a readable `provider_unavailable` message and exit code `3` until you explicitly select a provider. For remote model inference, select an HTTPS endpoint and model and acknowledge external manuscript disclosure:

```bash
python3 -m aeonith.workflow --input draft.md --title "Draft" \
  --provider openai-responses --url https://api.openai.com/v1/responses \
  --model YOUR_COMPATIBLE_MODEL --allow-external-disclosure \
  --output review.md
```

Set `AEONITH_PROVIDER_API_KEY` securely if the chosen provider requires it. The flag is a local disclosure acknowledgment, **not** a host-authenticated consent record or a cost guarantee. Output paths are reserved exclusively and not overwritten. See the [reader workflow guide](docs/READER_WORKFLOW.md).

From the repository root, with Python 3.11 or later:

```bash
python3 -m aeonith review --input examples/microfiction.json
```

With no provider configured, the command prints JSON with `"status": "provider_unavailable"` and exits with code `3`. This is intentional: structural processing without a language model is not literary criticism.

To run an actual review, choose a trusted service implementing the compatible chat-completions endpoint and configure its full URL, model, and optional key through your environment or secret manager:

```bash
export AEONITH_PROVIDER_URL="https://provider.example/v1/chat/completions"
export AEONITH_PROVIDER_MODEL="your-supported-chat-model"
# If required, supply AEONITH_PROVIDER_API_KEY via your secret manager.
python3 -m aeonith review \
  --input examples/microfiction.json \
  --provider openai-compatible
```

The URL above is a **placeholder**; substitute an actual endpoint and model you control or are authorized to use. The adapter requires HTTPS for remote endpoints and permits unauthenticated local HTTP for development. It does not follow HTTP redirects. Do not provide confidential manuscripts to a third-party provider without reviewing that provider's processing and retention terms.

For an explicitly chosen model compatible with the OpenAI Responses API, select the other adapter:

```bash
export AEONITH_PROVIDER_URL="https://api.openai.com/v1/responses"
export AEONITH_PROVIDER_MODEL="your-selected-compatible-model"
# Set AEONITH_PROVIDER_API_KEY securely in your environment if required.
python3 -m aeonith review --input examples/microfiction.json --provider openai-responses
```

This is a configuration example, **not a claim of a verified live API call**. For Chat Completions models that reject the legacy token/temperature fields, use `--token-field max_completion_tokens --omit-temperature` if that matches their documented parameters. Use `--json-mode` only for compatible chat endpoints; JSON mode does not prove schema compliance.

Use `--structured-outputs` with `python3 -m aeonith review` to request a strict JSON Schema for supported models, while keeping Aeonith's independent quote and lens validation. See [structured-output compatibility](docs/STRUCTURED_OUTPUTS.md).

To critique a plain UTF-8 manuscript and read the output as Markdown:

```bash
python3 -m aeonith.text_input --input draft.md --title "Draft" > request.json
python3 -m aeonith review --input request.json --provider openai-responses > review.json
python3 -m aeonith.formatting --input review.json --title "Draft" > review.md
```

The converter and renderer are local and make no provider calls; only the middle command does. Keep `request.json`, `review.json`, and `review.md` private if the work is private. If the review fails, the renderer reports an unavailable critique instead of inventing one and preserves a nonzero exit code.
In shells configured with `set -e`, a failed review stops the three-step workflow before rendering; inspect the JSON error, or invoke the renderer separately for a readable failure explanation.

You can also send a JSON request on stdin:

```bash
printf '%s\n' '{"schema_version":"aeonith.review.v1","work":{"title":"A draft","text":"The door opened, but nobody entered."}}' \
  | python3 -m aeonith review --input - --provider openai-compatible
```

The CLI returns structured JSON. The core is also importable:

```python
from aeonith import critique

request = {
    "schema_version": "aeonith.review.v1",
    "work": {"title": "Draft", "text": "The door opened, but nobody entered."},
}
result = critique(request, provider=my_explicitly_configured_provider)
```

`provider` is an injected object with a `review(payload: dict) -> dict` method. Omitting it produces a truthful `provider_unavailable` result.

## Output and evidence boundaries

The core requests one item per selected critical lens (`lens_reviews`), with `analysis`, `basis`, `support`, and `limitations`, plus an overarching `synthesis`. It supports a subset of the fourteen lenses for focused review, but a complete default request covers all fourteen. A lens may explicitly state insufficient textual evidence instead of inventing a finding.

The core checks that each `support` quotation is an exact substring of the submitted work or that a referenced supplied-evidence ID exists. It does **not** verify the truth of an external citation, a model's account of history, inferred author intent, or the literary merit of an interpretation. `evidence_audit` labels supplied evidence as unverified unless independently checked elsewhere.

Use `aeonith.evidence.audit_review_spans(work_text, completed_result)` for an optional, separate `aeonith.quote_locations.v1` index that locates exact quotes, records ambiguous duplicate occurrences, and fingerprints the source. It does not rewrite the v1 result or choose an intended passage where multiple matches exist. See [source-anchor behavior](docs/SOURCE_ANCHORS.md).

For longer writing, `python3 -m aeonith.longform --input book.md` plans bounded excerpts, preserving Unicode offsets and exact source coverage without invoking a model. `aeonith.longform.build_segment_request` prepares a selected excerpt for the existing v1 critic. It does **not** evaluate relationships across unseen chapters. See [long-form planning](docs/LONGFORM.md).

Review output is **advice**, not an authoritative rewrite or a command to change manuscripts, lore, memory, or other ecosystem state. The invocation envelope's `request_id` is a correlation value, not consent, authentication, durable replay protection, or provider attestation.

## Current boundaries

The original GPT has broader configurations than this repository implements. The repository currently **does not** provide:

- ChatGPT's general-conversation interface, canvas, or web research;
- the original GPT's attached knowledge-file corpus or retrieval workflow;
- creative Trickster activation or its private trigger;
- the image-refinement/Realism generation workflow;
- semantic chapter comprehension, automatic cross-chapter synthesis, manuscript revisions, or a human-calibrated literary-quality score;
- a running network service, MCP server, CCB delivery, Rezon deployment, or host-owned authorization.

These are candidate follow-on interfaces, not completed capabilities. Publishing the GPT's attached references would also require a per-file ownership, privacy, and redistribution-rights review. The original GPT's instructions and a private activation phrase are deliberately not included here.

The [sanitized functional specification](docs/AEONITH_PUBLIC_SPEC.md) records what the authenticated editor exposed and which claims remain unverified. [Ecosystem integration research](docs/INTEGRATION_RESEARCH.md) and [literary evaluation research](docs/RESEARCH_QUALITY.md) provide proposed improvements and their evidence—not proof of runtime quality.

## Test and qualification

Run the local standard-library suites after installing or checking out the source:

```bash
python3 -m unittest discover -s tests -v
```

Structural tests cover lens identity, invalid/unknown references, rejected fabricated quotations, missing-provider behavior, provider errors, and CLI failure status. Their pass does **not** establish semantic accuracy or subjective literary quality. A live-provider assessment should compare fixed, consented passages to the original GPT using human-rated textual fidelity, lens distinctness, useful critique, counterreadings, and stability across repeated samples. Record the exact model/provider and date; do not compare model output on a private manuscript without its owner's consent.

The [offline evaluation bench](evaluation/README.md) adds quote/reference audits, duplicate-analysis warnings, seeded blinded A/B comparison files, display-hash-bound human annotations, descriptive aggregation, and a six-dimension rubric. Run `python3 evaluation/quality_eval.py --help`. These utilities do not call a provider, verify human independence, infer model identity, score literary truth, or replace human assessment. Do not publish blinded displays containing private manuscript text.
The `evaluation/` scripts and experimental `integrations/host_gate.py` are **source-checkout tools**, not modules packaged in the installable `aeonith` wheel.

## Research and ecosystem direction

Initial design choices favor traceable text evidence, honest abstention, and author-controlled revision. The [KRISTEVA close-reading benchmark](https://aclanthology.org/2025.acl-long.1577/) and [literary evidence retrieval research](https://aclanthology.org/2025.acl-short.29/) illustrate why deep literary interpretation and source-grounded quotation remain challenging. Public tools such as [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) and [Promptfoo](https://github.com/promptfoo/promptfoo) offer future evaluation options, without being required runtime dependencies.

Optional integration with Rezon, CCB, or other repositories should use the documented typed contract, explicit host permission, and source provenance. It must not silently copy protected code, private manuscripts, or copyrighted GPT knowledge files.

An [experimental host-gate contract](docs/HOST_BOUNDARY.md) and source-only adapter in `integrations/host_gate.py` illustrate authorization and budget reservations. **It is not an identity provider, host attestation, metering service, deployed permission mechanism, or standalone security boundary.** It must not be enabled until a separately authenticated host implements the documented controls.

## Licensing

This repository has no published license at this stage. Publicly readable source is **not automatically open source** and does not grant unrestricted redistribution rights. A license and third-party-asset policy require a deliberate owner decision.
