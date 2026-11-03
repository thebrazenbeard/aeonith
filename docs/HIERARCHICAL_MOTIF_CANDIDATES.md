# Opt-in hierarchical motif candidates (source only)

`aeonith.hierarchical_review.derive_cross_section_motif_candidates` is an
optional **offline, deterministic** follow-up to a completed or partial
`review_longform_plan` / `review_checkpoint_plan` batch. It does **not** run a
model, contact a service, or create a whole-book critique.

The current segment batch has a coverage-oriented
`cross_segment_evidence_index`. That index alone cannot establish whether a
passage from section one is thematically connected with another section. Nor
does an individual critique's `synthesis` establish a whole-book reading.

## Private caller example

```python
from aeonith.book_review import review_longform_plan
from aeonith.hierarchical_review import derive_cross_section_motif_candidates
from aeonith.longform import plan_longform

# `manuscript` stays caller-owned. `provider` is independently configured and
# intentionally injected; book review itself does not select a cloud provider.
plan = plan_longform(manuscript, max_chunk_chars=20000)
report = review_longform_plan(manuscript, plan, provider=provider, max_segments=8)
motifs = derive_cross_section_motif_candidates(
    manuscript, report, ["silver bell", "open door"],
    canonical_eligible_plan=plan,
)
```

The caller supplies literal phrase hypotheses. For each one, the module
verifies the batch source SHA-256, excerpt offsets and per-excerpt SHA-256,
rechecks the actual source quotations, and cross-checks the normalized
`work` support rows against the batch's evidence index. Only **exact,
case-sensitive** phrase occurrences inside validated literal work quotations
count. A phrase must occur in at least two distinct source sections to yield
`recurring_literal_candidate`.

`canonical_eligible_plan` is an **optional, caller-owned** `plan_longform`
output. When supplied, the module independently reruns `plan_longform` over
the supplied eligible source and its exact title/chunk/request limits; it
requires an equal plan, including canonical section boundaries and segment
IDs, then binds every report segment's offsets and digest to those canonical
segments. This closes a forged-but-self-consistent report counterexample
where the report shrank an excerpt to a real quote, recomputed its hash, and
preserved `completed_segments` counters. A mismatch raises
`HierarchicalReviewError` without quoting private source. This verification
is offline and makes no service or model call.

For a checkpoint review, pass `checkpoint_plan["excerpt_plan"]` as the
`canonical_eligible_plan` and **only the eligible post-marker source text** as
the source. This verifies the eligible-source partition, not the marker's
position in the omitted full manuscript; `checkpoint_marker_authenticated`
remains false. Revalidating the marker requires the original whole source and
the separate checkpoint planner, outside this private candidate generator.

Output is bounded to 16 phrases, at most 512 report-declared planned segments and 4096
validated work-quote anchors. It contains only phrase hashes, section/segment
identifiers, source and quote SHA-256 hashes and coverage metadata—**no raw
manuscript, critique prose or phrase strings**. It does not create files or
logs. Retain the input report and the original source privately: hashes alone
do not reconstruct a literary argument.

## Boundaries

- `semantic_status` and every `semantic_interpretation` are always `UNKNOWN`.
  Repeated words can be coincidental, ironic, or narratively unrelated.
- No matches, one matching section, malformed provenance or unsupported
  scope never become a favorable theme verdict. Invalid provenance raises
  `HierarchicalReviewError` without quoting private source text.
- Only completed, quote-grounded excerpts are considered. For any completed
  excerpt, `coverage.status=report_declared_coverage_unverified` and
  `reported_segment_status` preserves the report's `complete`/`partial`
  arithmetic without authenticating original segment boundaries. `none` means
  no reviewed source anchors. Even a self-consistent report can shorten an
  excerpt to a real quote and recompute hashes. Sections are heuristic, not
  independently authenticated chapters.
- With a matched optional canonical eligible plan, the status changes to
  `canonical_partition_verified_report_declared_complete` (or `_partial` /
  `_none`). This means the **partition** now matches a replayed deterministic
  source plan and the report's own counters claim completion. It does **not**
  prove any model invocation occurred, provider identity, literary quality,
  human judgment, checkpoint prefix custody, or semantic interpretation.
- `provided_evidence` references are **never** counted as literal work-quote
  anchors, even when a provider's segment critique used them.
- For checkpoint reviews, supply **only the exact eligible post-checkpoint
  source** (`report.source_sha256`), not the full document containing the
  excluded prefix. This prevents accidental inclusion of excluded material.
- Source hashes and original checked quotations establish byte/substring
  consistency of the supplied report with the supplied source. They do not
  authenticate the author, the source's rights, provider honesty, or the
  accuracy of a literary interpretation.

This is preparation for a later, separately qualified *candidate* literary
analysis workflow. No semantic hierarchical synthesis is represented as
implemented here.
