# Aeonith lens-specific critical methods (v0.3 proposal)

The `aeonith.review.v1` output schema and its fourteen canonical lens names are
unchanged. The source package now sends a `lens_methods` object to the
explicitly configured model adapter alongside existing `lens_guidance`.
Only requested lenses are sent, and each includes:

- `observe`: a concrete question about supplied text that should be
  answered from a short, exact passage;
- `counterread`: a plausible competing interpretation or mechanism worth
  testing *when the text supports one*;
- `limit`: a reason to abstain or qualify an inference rather than invent
  literary, historical, psychological or audience facts.

The general instructions now require the model to distinguish directly
observable wording from interpretations, connect quotes to local effects,
prioritize useful tensions in the synthesis, and leave revision choices to the
author. Different lenses investigate different mechanisms; they do not
receive an automatic pass for producing fourteen sections.

## Compatibility

- Existing `CriticProvider.review(payload) -> dict` remains unchanged.
- Existing `aeonith.review.v1` result, status and provenance contracts remain
  unchanged. No second model, web search, retrieval or hidden GPT knowledge
  has been added.
- The extra `lens_methods` field appears only in the provider's task input.
  Generic providers may ignore it, and stricter third-party adapters that
  whitelist task keys may need to accept the optional field.
- Text and context remain untrusted task data, not executable instructions.
- The additional prompt material increases input-token cost; a real provider
  and context-window qualification must be performed before promising
  compatibility or latency.

## Verification boundary

The dedicated contract tests verify all fourteen methods, selected-lens
payloads, untrusted text isolation, honest abstention for thin historical
context and anchored counterreadings with unverified provenance. Existing
v0.2 tests continue to pass with the candidate core substituted.

> A better prompt can elicit a richer critique, but it cannot establish that a
> model actually reasons well. A generic response repeated fourteen times
> still passes the existing core's structural checks; the offline quality
> auditor warns about such repetition, and actual improvement needs blinded
> human/author evaluation against a controlled baseline.

No live model, private manuscript or paid API call was used for this slice.
