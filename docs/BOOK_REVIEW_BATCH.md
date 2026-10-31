# Bounded provider-opt-in long-form review batches

Aeonith can execute a set of excerpt reviews against an explicitly injected
provider using a canonical exact-source plan. This is not a whole-book
synthesized judgment, automatic cross-chapter retrieval or autonomous service.

## Python example

    from aeonith.longform import plan_longform
    from aeonith.book_review import review_longform_plan

    manuscript = "# Chapter 1\nA note.\n\n# Chapter 2\nAnother note."
    plan = plan_longform(manuscript)
    result = review_longform_plan(manuscript, plan, provider=approved_provider)

With no provider, status is provider_unavailable and attempted_segments is zero.
No review is fabricated. The provider must be intentionally chosen and
disclosure of manuscript excerpts permitted before calling it.

To review only after an author marker:

    from aeonith.checkpoint import plan_after_checkpoint
    from aeonith.book_review import review_checkpoint_plan

    plan = plan_after_checkpoint(manuscript_with_ps)
    batch = review_checkpoint_plan(
        manuscript_with_ps, plan, provider=approved_provider,
        marker="[ps]", max_segments=64,
    )

The post-checkpoint operation sends ONLY the text following the unique marker
to the model, not the preceding material. max_segments is a strict, whole-batch
preflight limit: 1 to 512, default 8. Exceeding it fails before any model calls.

## What the return fields mean

- planned_segments: number of canonical excerpts.
- attempted_segments: critique invocations made.
- completed_segments: structurally validated core results with status completed.
- attempted_chars / completed_chars: original non-overlapping Unicode characters,
  NOT model tokens, pages, or confirmed literary insight.
- status segments_completed: every planned segment individually passed the
  existing structured response checks, NOT a whole-book evaluation.
- whole_book_synthesis: always null; no cross-chapter synthesis is claimed.
- reviews: full private per-segment results; they can reproduce manuscripts
  and spoil future scenes. Caller must control disclosure and display.

A failed/fabricated provider result stops subsequent calls, preserves the
successful prefix and reports incomplete. Stale source, tampered plan and
overbudget batches fail before any provider call. A matching quotation does
not establish that the model's interpretation is correct.

These are deterministic/fake-provider tests only. No live-provider
interoperability, original GPT parity, or independently measured literary
quality is established by this batch runner.
