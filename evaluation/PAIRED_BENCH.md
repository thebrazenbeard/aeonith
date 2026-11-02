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
hidden prior exposure and human-evaluator independence are not.

```bash
python -m evaluation.paired_model_bench prepare \
  --bundle /private/paired-runs.json \
  --output /private/paired-outputs-new
```

All validation finishes before any output is created. The output directory
must not exist and must be outside the Aeonith checkout. New `pairs/`
blinded displays and separate `keys/` model assignment files, plus a text-free
`bench_receipt.json`, are created exclusively with owner-only permissions on
POSIX. On Windows, assess actual ACLs and the sharing privileges of the parent
directory; filesystem modes are not a security boundary there. A crash may
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
