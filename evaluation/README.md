# Aeonith literary critique evaluation bench

This is an **offline, provider-neutral** test bench for the independently
implemented `aeonith.review.v1` response contract. It does not invoke a model,
require a key, transmit manuscript text, validate external citations, or claim
to measure literary truth. Python standard library only.

## What it checks

1. Every explicitly requested canonical lens appears exactly once; support and
   explanatory fields follow the review contract.
2. Work quotations must be exact substrings of the input. Evidence references
   must be IDs present in caller-provided evidence. Presence of an ID is **not**
   external verification of that source's accuracy.
3. Exact, case-insensitive duplicate lens analysis is flagged as a **heuristic
   warning**, not automatic evidence of poor criticism. A response with 14
   identical lens paragraphs can pass the hard structural checks, but receives
   an obvious repeat-filler warning. Superficially rewritten generic filler
   remains a human review question.
4. A provider failure is `not_evaluable`, not a judgment on artistic quality.

The audit's `semantic_quality` is always `UNASSESSED`. A structurally valid
critique can still be banal, culturally insensitive, or fundamentally wrong.

## Commands

From the repository root, with your own original or permissioned JSON input:

```bash
python -m unittest discover -s tests -p 'test_quality_eval.py' -v
python evaluation/quality_eval.py audit \
  --request request.json --review model_a.json
python evaluation/quality_eval.py blind \
  --request request.json --first model_a.json --second model_b.json \
  --first-id candidate-v1 --second-id candidate-v2 \
  --display-out blinded_pair.json --key-out private_assignment.json \
  --seed experiment-001
python evaluation/quality_eval.py validate-annotation \
  --pair blinded_pair.json --annotation human_annotation.json
python evaluation/quality_eval.py bind-annotation \
  --pair blinded_pair.json --annotation human_annotation.json \
  --out private_bound_annotation.json
python evaluation/quality_eval.py aggregate \
  --study local_human_study.json --out private_study_summary.json
python evaluation/quality_eval.py manifest \
  --request request.json --review model_a.json \
  --provider-id provider-name --model-id model-version \
  --code-revision git-sha --prompt-revision prompt-v1 \
  --parameters decoding_parameters.json --out run_manifest.json
```

### Precommitted literary challenge-run accounting (source-only; not yet run)

`docs/LITERARY_QUALITY_GATE.md` defines 18 original tiny passages and a
two-candidate, two-lane protocol. A small **standard-library-only** harness
extracts those exact cases from that document. It does not use benchmark data
to fine-tune a model or infer a literary truth score.

```bash
# Offline: creates a new source-grounded 3-case × 2-candidate × 2-repeat plan.
python -m evaluation.literary_gate plan \
  --candidate incumbent --candidate challenger --phase screen \
  --out screen-plan.json

# Only on an owner-qualified machine with an already-running local model:
# Explicit --host-qualified is the operator's assertion, NOT an automated check.
python -m evaluation.literary_gate run \
  --plan screen-plan.json --candidate incumbent --model your-local-model-name \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --lane production --host-qualified --out private-incumbent.jsonl
# Repeat run with the other candidate and its own local model/runner.

# Offline: every scheduled slot counts even when its attempt failed or is missing.
python -m evaluation.literary_gate account \
  --plan screen-plan.json --first private-incumbent.jsonl \
  --second private-challenger.jsonl --out private-attrition.json

# Offline: only structurally valid paired responses become blind displays.
# Keep the assignment key in a different access-controlled directory.
python -m evaluation.literary_gate blind \
  --plan screen-plan.json --first private-incumbent.jsonl \
  --second private-challenger.jsonl --seed study-seed-v1 \
  --out reviewer-displays.json --key-out private/assignment-keys.json
```

`--phase full` freezes 18 cases × three repeats × two candidates = 108
scheduled attempts. Both phases include the **same two candidates**, and each
candidate must be run in a separate private journal. A run's full 0600 JSONL
journal contains original synthetic passages and **raw model prose**; the
accounting output omits both and reports `structural_pass`, `structural_fail`,
`provider_noncompletion`, `interrupted`, and `not_attempted` against the complete denominator.
Model failures are recorded, not hidden behind a successful A/B pair rate.
Journal writes are flushed and synchronized after each attempt; a crash is
distinguished from an unstarted slot when a start receipt was persisted. Run on
owner-controlled encrypted/access-restricted storage, outside Git; `.gitignore`
cannot prevent an operator from explicitly adding a private result file.

This harness can only attest the operator **said** the host had spare
resources, rights to the model and no contested training/service workloads. It
does not inspect real CPU/GPU process ownership, spend, licenses or privacy
settings, and must not be invoked before those are independently checked.
The local provider rejects remote, credentialed, redirected, and proxy-routed
HTTP. Real model latency, semantic insight, blinded human ratings, and host
qualification remain unassessed. Repeated identical model outputs get unique
attempt-instance pair IDs for downstream annotations; repetitions remain
correlated observations, not independent literary works.

`audit` exits 1 on hard failures, while warnings are nonfatal by default.
Use `audit --fail-on-warnings` to opt into a stricter policy gate (exit 3),
recognizing its false-positive risk. `blind`
writes a reviewer-facing display and a **separate private assignment file**.
Both are created with owner-only permissions (0600) on POSIX; the destination
directory must still be controlled and protected against other processes.
Structurally invalid candidate reviews are rejected before blinding, and
only validated literary fields are projected. Identity clues in free-form
prose still need manual scrubbing. Existing files are never overwritten. Do not give the private assignment file
to annotators until all A/B judgments are locked. Use permissions or a separate
access-controlled directory if running a shared study. The seed is a
reproducibility control, not a secret or proof of randomness.
`manifest` also creates a new file without overwriting. Its parameter JSON
should contain only non-secret scalar settings such as `temperature` or
`max_output_tokens`; never credentials, manuscript text, or raw prompts.
`aggregate --out` likewise creates an owner-only (0600 on POSIX), exclusive
summary file. Directing stdout with shell `>` may instead create a
world-readable file under the shell's umask.

### Offline human-study aggregation

`aggregate` consumes one private JSON study bundle:

```json
{
  "schema_version": "aeonith.human_study_bundle.v1",
  "records": [
    {
      "pair": {"schema_version": "aeonith.blind_pair.v1", "pair_id": "...",
               "request": {}, "A": {}, "B": {}, "directions": "..."},
      "annotations": [{
        "schema_version": "aeonith.study_annotation.v1",
        "display_sha256": "<sha256 of canonical A/B display JSON>",
        "annotation": {"schema_version": "aeonith.human_annotation.v1",
                       "pair_id": "...", "reviewer_pseudonym": "...",
                       "dimensions": {}, "preference": "tie", "rationale": "..."}
      }]
    }
  ]
}
```

The example shows the shape only; use the complete `blind` display and
`human_annotation.schema.json`-validated annotations in a real bundle.
`human_study_bundle.schema.json` documents the outer structure; the Python
aggregator also rejects duplicate pair IDs, duplicate reviewer pseudonyms
within a pair, mismatched annotations, and malformed ratings. The
`study_annotation.schema.json` receipt is required: generate it with
`bind-annotation` at annotation collection time, using **the same A/B display
JSON content** the reviewer was given. The hash covers canonicalized JSON
content; it does not prove which presentation bytes were rendered or viewed.
Two opposite A/B orientations can share a `pair_id`
because the ID identifies the underlying comparison, so the display SHA-256
is necessary to catch accidental annotation mixing across orientations.
This content hash is not a signed viewing receipt; the study operator
must still preserve a trustworthy association between a reviewer's
record and the screen they saw.

The result contains per-pair rating **sums and counts**, preference counts,
and a simple disagreement indicator when at least two comparable judgments
exist. It omits manuscript text, candidate identities, reviewer pseudonyms,
and free-form rationales. Records are sorted by pair ID so input-file order
cannot change the output. An empty study reports `no_data` (CLI exit 3).
Pair IDs and display hashes are still linkable content fingerprints, so keep
even the summary private if membership or equality of a sensitive work matters.
No confidence intervals, statistical significance, model ranking, or truth
claims are computed. **A/B are presentation positions, not candidate IDs**;
never treat more `A` votes as proof that a model won. The operator remains
responsible for author/reviewer permission, genuine independence, and keeping
the raw study bundle and separate identity key in a restricted location.

The original cases in `original_cases.json` are newly authored, short texts
created for this benchmark, not copies of third-party literary works. The
repository owner has not selected a redistribution license yet. Their phenomenon tags are possible
interpretations for study design, **not an oracle of correct meanings**.

## Human evaluation protocol

1. Pre-register tasks and selection criteria. Sample across short fiction,
   poetry, dialogue, ambiguous passages, and intentionally insufficient
   fragments. Reserve distinct prompts and works for holdout evaluation.
2. Give the same request, source evidence, and limits to every candidate;
   record real provider/model IDs, immutable code and prompt revisions,
   generation parameters, and input/output SHA-256 hashes with
   `make_manifest()` (caller-declared provenance, not verification).
3. Audit outputs; report hard failure rates, unsupported quote/ref rates,
   lens coverage, and repeat-filler warnings separately from human scores.
   Do **not** remove losing candidates without documenting exclusions.
4. Create blinded A/B pairs. Randomize order using several precommitted seeds
   and intentionally evaluate order swaps. Hide model identity; scrub any
   self-identifying prose manually. The field allowlist removes metadata but
   cannot reliably strip identifiers quoted inside free-text critique.
5. Recruit multiple independent reviewers where feasible. Ask each to score
   both A and B on the six dimensions below (0=poor, 1=mixed, 2=strong),
   record `A`/`B`/`tie`/`incomparable` and an evidence-based rationale. Store
   annotations as in `human_annotation.schema.json`. Disagreements, ties,
   calibration issues, and order effects are results, not defects to conceal.
6. Analyze rankings with paired outcomes and confidence intervals; stratify
   by genre, passage length, evidence quality, and lens. Report small-sample
   limitations. Retain raw anonymized judgments for replication with consent.

| Dimension | Human question |
| --- | --- |
| `textual_accuracy` | Does the criticism accurately represent the given words and distinguish inference from observation? |
| `lens_distinctness` | Does each lens contribute a recognizably different critical method instead of generic 14-lens filler? |
| `critical_depth` | Are the interpretations precise, reasoned, charitable, and willing to challenge the text? |
| `calibration` | Does it admit ambiguity, alternative readings, and missing context without inventing facts? |
| `actionability` | Where revision advice is appropriate, is it specific and proportional rather than arbitrary? |
| `synthesis` | Does the whole review integrate tensions, strengths, weaknesses, and broader significance? |

## Research and reuse boundaries

- **KRISTEVA**: [ACL 2025, 1,331 close-reading questions](https://aclanthology.org/2025.acl-long.1577/) motivates testing evidence-based reasoning, context, and multi-hop interpretation. Our synthetic fixture set is not that benchmark.
- **Literary Evidence Retrieval**: [ACL 2025, 292 verified examples](https://aclanthology.org/2025.acl-short.29/) motivates testing exact textual support separately from impressionistic critique. We do not claim a substring check is a sufficient evidence-retrieval metric.
- **LongStoryEval**: [ACL 2025, book-length story evaluation](https://aclanthology.org/2025.acl-long.799/) motivates eventual chapter-aware, long-context testing. This short-input harness makes **no** book-length coverage claim.
- [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) (MIT) and [promptfoo](https://github.com/promptfoo/promptfoo) (MIT) show useful patterns for repeatable evaluations and human-in-the-loop comparisons. **No code or benchmark data copied** from either project.

Production benchmarks should add genre-appropriate consented/redistributable
works, independent literary experts, and blind inter-rater studies. Never place
user manuscripts, unlicensed texts, secrets, or unconsented model outputs into
a public repository or telemetry system.

## Boundaries and known limitations

- Exact-quote checks catch fabricated quoted spans, not a plausible yet false
  paraphrase. The system does not verify external reference truth or evidence
  content; a model could cite an input reference inappropriately.
- A repetitive paraphrase can evade exact-duplicate warnings; use rubric-based
  human assessment for meaning and distinctiveness.
- Blinding is best effort. The display strips conventional metadata fields;
  self-identifying prose must be manually scrubbed under a documented rule.
- Deterministic order assignment is not independent reviewer randomization;
  avoid correlated order effects and test both orientations.
- Manifest hashes prove byte-level consistency for the provided JSON values,
  not provider authenticity or that a model performed the critique.
- Descriptive score totals, counts and basic disagreement are automated;
  statistical significance, verified reviewer independence and literary
  validity are **not**. Sample selection remains a human research decision.
