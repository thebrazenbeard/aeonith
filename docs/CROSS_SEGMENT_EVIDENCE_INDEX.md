# Cross-segment evidence index (not a synthesized review)

`review_longform_plan` and `review_checkpoint_plan` now return
`cross_segment_evidence_index` alongside the private, individual excerpt
reviews. The index is a deterministic source-coverage map, **not** an
additional model generation, whole-book interpretation or semantic score.

- Every heuristically detected section lists its exact planned segment IDs,
  source fingerprints, and `not_attempted`, `completed`, or observed failure
  statuses. An index is `fully_indexed_excerpts` only if **every** segment
  critique completed; otherwise it is partial or not attempted.
- A completed review contributes its normalized lens identifier, basis,
  literal quote SHA-256 digest and quote character count. The full private
  review retains the actual quote. The index omits quoted passage bodies,
  model analysis and unverified thematic conclusions. **Section labels are
  source-derived and may themselves contain verbatim manuscript headings.**
  Short-quote digests and source fingerprints may also be vulnerable to
  guessing attacks against known passages.
- `lens_coverage` records only which source sections supplied literal work
  quotes for each lens. It does **not** claim a lens is meaningful, an
  interpretation is correct, or different sections share a theme.
- `offset_scope` is `full_submitted_source` for regular long-form review and
  `eligible_post_checkpoint_source` for checkpoint review. In the latter
  case no excluded prefix text, marker or original-source offset is emitted.
- `whole_book_synthesis` and the index's `whole_book_interpretation` remain
  `null`; `semantic_relationships` remains `UNASSESSED`.

No extra model call is introduced. Source planning, request budgets and the
first-failure stop rule remain unchanged. Treat every returned review and
index as private author/editor data; do not emit it as public metrics, logs or
repository artifacts. Retain independent human literary
quality evaluation as a separate gate.
