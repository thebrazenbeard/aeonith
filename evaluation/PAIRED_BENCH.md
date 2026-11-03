# Offline paired-model evaluation preparation

`python -m evaluation.paired_model_bench` is a **source-only, offline** tool for
auditing *already generated* frozen-base and adapter responses on work-level
holdouts. It neither loads a model nor runs inference; no weights, Hugging Face,
KoboldCpp, Ollama, remote API, credentials, or Supabase are contacted. A passing
receipt is **not** evidence that the declared models executed or that any LoRA
improved literary reasoning.

## Prepare a comparison

An authorized operator first obtains at least two genuinely distinct,
sequestered literary works and runs the **same prompt, decoding parameters,
code/prompt revisions, and seed** through the frozen base and its adapter.
Repeat for at least two distinct seeds on *every* holdout work. Record all
attempted runs, including failed generations; do not select only successes.
Keep manuscript and inference outputs outside Git.

Create an offline UTF-8 JSON object with this structure (shortened example;
all SHA fields are 64 lowercase hexadecimal characters and actual responses
must follow `aeonith.review.v1`):

```json
{
  "schema_version": "aeonith.paired_model_bench.v1",
  "experiment_id": "private-study-01",
  "model_identities": {
    "base": {"model_id": "base-v1", "weights_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    "adapter": {"model_id": "adapter-v1", "weights_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
  },
  "split_inventory": {
    "train": [{"source_id": "train-work", "work_sha256": "<sha256 from evaluation.quality_eval.digest(work_text)>"}],
    "validation": [{"source_id": "dev-work", "work_sha256": "<sha256 from evaluation.quality_eval.digest(work_text)>"}],
    "holdout": [
      {"source_id": "unseen-work-1", "work_sha256": "<digest(work_text)>"},
      {"source_id": "unseen-work-2", "work_sha256": "<digest(work_text)>"}
    ]
  },
  "runs": [
    {
      "source_id": "unseen-work-1",
      "seed": 11,
      "request": {"schema_version": "aeonith.review.v1", "work": {"text": "private passage"}, "lenses": ["symbolic"]},
      "base_review": {"status": "provider_unavailable"},
      "adapter_review": {"status": "provider_unavailable"},
      "base_manifest": {"<replace>": "real evaluation.quality_eval.make_manifest(...) return"},
      "adapter_manifest": {"<replace>": "real evaluation.quality_eval.make_manifest(...) return"}
    }
  ]
}
```

The shortened sample is intentionally **not runnable**: include complete
`aeonith.review.v1` responses, corresponding `make_manifest()` records and
the full work × seed grid. The manifest must cryptographically match the
request and response content, identify the expected model, and record the
same seed and decoding configuration. Its metadata remains
`CALLER_DECLARED_UNVERIFIED`; cryptographic content hashes do **not** prove
which process generated the output.

Before generating input, pre-register holdout works and seeds and keep the
holdout independent of any training, validation, prompts selected during
development, or previous output revisions. Exact source-ID and work-text
hash separation is mechanically checked; semantic paraphrase contamination,
hidden prior exposure and human-evaluator independence are not. Document
the author/rightsholder's permitted evaluation uses and any redistribution
restrictions in a **private** custody record; a text hash is not a license.

```bash
python -m evaluation.paired_model_bench prepare \
  --bundle /private/paired-runs.json \
  --output /private/paired-outputs-new
```

All validation finishes before any output is created. The output directory
must not exist and must be outside **every** Git repository, including bare
repositories and other worktrees. New `pairs/` blinded displays and separate
`keys/` model assignment files, plus a text-free `bench_receipt.json`, are
created using pinned directory handles and exclusive owner-only files on
supported POSIX hosts. **Windows export fails closed** until a separately
verified anti-reparse/owner-DACL writer exists; Unix modes do not qualify
Windows permissions. A crash may
leave an incomplete output directory without a final receipt; inspect it and
do not reuse it silently. Never publish the output folder or give `keys/` to
human raters before their annotations are locked.
Even the text-free receipt contains linkable hashes and pair IDs; keep it
private if the membership of an evaluated work is sensitive.

## Honest outcomes and human assessment

- The receipt includes **every attempted run**, its structural status for
  base and adapter, and a count of comparisons eligible for blinding.
  Provider failures and malformed critiques stay in the denominator; they
  are not counted as semantic failures or silently discarded.
- Only two structurally valid critiques create a blind pair through
  `evaluation.quality_eval.build_blind_pair()`. Blinding strips conventional
  metadata but cannot remove identifying language embedded in model prose.
- If two seeds produce identical outputs, the underlying content-only pair
  identifiers would collide, possibly with **opposite** A/B orientations.
  The tool deterministically derives a **run-qualified pair ID** from that
  content ID plus the experiment/source/seed run identity. Both the blinded
  display and its corresponding private key carry the same new ID; the key
  also retains `source_content_pair_id`. The receipt reports repeated content
  pairs, which remain repeated evidence even though the run IDs are distinct.
  Do not count identical generations as independent literary insights.
- Use the existing `quality_eval.py validate-annotation`, `bind-annotation`
  and `aggregate` interfaces to collect blinded human ratings and assess
  disagreement. The assignment keys should be revealed only *after* ratings
  have been locked, under custody appropriate for sensitive manuscripts.
- No automatic model ranking or literary-quality claim is emitted. Real
  source and evaluation custody, verified model invocation, human literary
  adjudication, and analysis of variance across withheld works/seeds remain
  separate obligations.

The current public Aeonith fixtures and the two exposed candidate holdouts
do **not** meet this protocol's truly unseen-work requirement. Reusing them
can test mechanics, but is not a valid independent generalization study.

## Private-blind human adjudication, without publishing the corpus

This protocol uses the existing offline commands; it does not score actual
literary merit without actual people reading authorized, genuinely unseen
works. In particular, the two historical public fixture timings and
schema-compliant critiques do not constitute a human result.

1. **Pre-register privately before candidate execution.** Record a random
   experiment ID, rights-holder/permission evidence for each source,
   train/dev/holdout work IDs and hashes, the source-level exclusion check,
   frozen model and adapter artifact digests, exact prompt/code revisions,
   same decoding configuration, at least two distinct withheld works, and
   at least two seeds per work. Seal the holdout list away from anyone tuning
   prompts, adapters, or evaluation thresholds. Record a missing or interrupted
   model attempt explicitly; do not silently replace a bad seed/output with a
   fresh favorable run. The `prepare` command rejects incomplete seed grids
   instead of fabricating data for missing attempts.
2. **Create output privately on a supported POSIX host.** Run `prepare` as
   shown above, with the complete local run bundle in an owner-only directory
   outside Git. Check that `bench_receipt.json` reports all attempted run
   slots and the base/adapter structural failures and non-evaluable counts.
   A receipt is a validation result, not attestation of the declared model
   process, rights, or holdout novelty.
3. **Quarantine identifiable output before handing anything to raters.** The
   operator inspects `pairs/*.json` for self-identifying model prose and
   fabricated quoted evidence. Keep `keys/` isolated; never give assignment
   keys or candidate labels to raters. Exclude compromised pairs from the
   blind comparison, but retain their failed/compromised run identities in the
   private study ledger and denominator. The tool strips ordinary metadata,
   **not** model names that a model writes in its own analysis.
4. **Get genuinely independent human judgments.** Use at least two people
   per surviving pair when possible, without access to assignment keys, each
   other's annotation, or model-selection work. Each completes
   `evaluation/human_annotation.schema.json`: six 0/1/2 A/B dimensions,
   A/B/tie/incomparable preference, and an evidence-based rationale. If a
   reader cannot judge the excerpt, `incomparable` is a valid outcome.
   AI/subagent critique is internal review, never a stand-in for human data.
5. **Validate and bind each human answer to the exact displayed orientation.**
   For a private pair and its private, human-authored rubric, run:

   ```bash
   python -m evaluation.quality_eval validate-annotation \
     --pair /private/study/pairs/PAIR.json --annotation /private/annotations/rater.json
   python -m evaluation.quality_eval bind-annotation \
     --pair /private/study/pairs/PAIR.json --annotation /private/annotations/rater.json \
     --out /private/bound/rater-pair.json
   ```

   Make a private `aeonith.human_study_bundle.v1` JSON object with one
   `{"pair": <exact pair JSON>, "annotations": [<bound rubric>, ...]}`
   record per pair (see `human_study_bundle.schema.json`). Aggregate offline:

   ```bash
   python -m evaluation.quality_eval aggregate \
     --study /private/study-bundle.json --out /private/blind-summary.json
   ```

   Before unblinding, compare the human study's exact oriented A/B pair IDs
   against **all** eligible run slots in the private model-bench receipt:

   ```bash
   python -m evaluation.paired_model_bench study-coverage \
     --receipt /private/study/bench_receipt.json \
     --study /private/study-bundle.json
   ```

   This read-only command reports the denominator including failed model runs,
   eligible pairs missing from the human packet, pairs with fewer than **two
   comparable, distinct-pseudonym rubrics**, and observed rater disagreement.
   It rejects additional unadmitted pair IDs, duplicate pair or run identities,
   inconsistent receipt run/seed grids, and annotations bound to a different
   A/B display orientation. Neither private manuscript text nor ratings,
   reviewer pseudonyms or rationales are printed.

   A result of `TWO_RATER_COVERAGE_OPERATOR_DECLARED` says only that the
   **submitted records** have complete coverage. Pseudonyms can be forged,
   receipt/model identity is caller-declared, and the command does not prove
   actual consent, reviewer independence, unseen-work novelty or stronger
   literary insight. `semantic_quality` remains `UNASSESSED` and it never
   computes a model ranking.

6. **Lock and review before unblinding.** Store original outputs, signed or
   otherwise verifiable human custody/consent records, and annotations in
   restricted storage, not Git. Use a human reviewer who did not select the
   comparison to challenge unsupported quotations, evaluator priming,
   model identity leaks, and paired-seed dependence. Treat disagreements,
   ties, exclusions, failed runs, and repeated identical generations as
   material findings. Only after judgments and exclusions are locked may
   an authorized custodian reconcile `keys/` to candidates; A/B-position
   aggregates do **not** themselves rank models. Report results by distinct
   held-out work and seed, with uncertainty; no automatic significance or
   generalization claim is produced.

The generated summary deliberately stays `semantic_quality: UNASSESSED`:
human numeric ratings are reported as *caller-provided judgments*, not as
independent proof that a model's literary reasoning improved. Current status:
**private holdout adjudication has not been executed** in the public source
tree, and no human quality scores are claimed.
