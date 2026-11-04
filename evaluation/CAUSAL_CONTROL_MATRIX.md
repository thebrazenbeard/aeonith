# Offline multi-arm control accounting (source-only)

`evaluation.causal_control_matrix.inspect_control_matrix(bundle)` checks a
**caller-declared** in-memory experiment record. It does not open private files,
invoke models, authenticate adapters, generate ratings, train Qwen, or establish
causal learning. The synthetic examples in `tests/test_causal_control_matrix.py`
are unit fixtures, **not** research results.

This complements `paired_model_bench`'s blinded **two-arm** literary-quality
study. It is a numerical accounting tool for controlled experiments once the
operator has separately obtained and authenticated actual model runs.

## Required preregistration

The strict `aeonith.causal_control_matrix.v1` object has:

- `experiment_id`, `outcome_origin` (`synthetic` or `operator_declared`), and
  `outcome_metric` (a named higher-is-better score scaled to `[0,1]`).
- `split_inventory` containing `train`, `validation`, and at least **two**
  genuinely withheld `holdout` works with distinct source IDs and SHA-256
  fingerprints. Exact source/hash overlap across the three splits is rejected.
- `arms` with distinct caller-declared `artifact_id` and `sha256` for
  `frozen_base`, `trained_adapter`, and `shuffled_feedback_adapter`.
  `disabled_head_adapter` is optional **only if that head exists in the model
  under investigation**. Aeonith's current ordinary LoRA has no appraisal
  head; do not fabricate a disabled-head result.
- A preregistered set of at least **two** distinct numeric seeds and one `runs`
  row for every holdout × seed × arm cell, including failures. Each row
  contains `source_id`, `seed`, `arm`, `request_sha256`, `status` (`observed` or
  `unavailable`) and `outcome` (`null` for unavailable). Identical request
  hashes across the arms of a work/seed are required; hashes do not attest the
  model process actually received that request.

The inspection returns an exact input digest, denominators, unavailable slots,
complete paired cells, and **descriptive** mean score differences from trained
to each control on complete pairs only. Missing outcomes are not secretly
imputed as zeros; no significance test or causal verdict is manufactured.

## Falsifiers and non-claims

1. A missing low-scoring run makes the grid **incomplete**; omitted rows are
   rejected rather than ignored.
2. A shuffled-feedback arm that reuses the trained adapter's declared bytes or
   artifact ID is rejected. Different digests alone still do **not** prove the
   feedback was actually shuffled or the run was independent.
3. A request fingerprint changed for one arm is rejected. Identical hashes are
   still merely caller-supplied assertions unless a host-owned executor binds
   requests, outputs, process identity and seed.
4. Exact train/holdout leakage is detected. Paraphrases, underlying prior
   exposure, training rights and semantic contamination remain unverified.
5. Unavailable or unscorable runs remain in the denominator. The mean covers
   only work/seed cells where **all** declared arms are observed, which can be
   highly selection-biased. A complete grid is not proof of improved quality.

For literary quality, use actual independent, blinded human assessments from
the paired study. For persistent model change, also require authenticated
weight provenance, a genuine optimizer update, a versioned adapter saved
through an approved broker, fresh-process reload, and recorded controlled
inference. This validator satisfies **none** of those operational gates.
