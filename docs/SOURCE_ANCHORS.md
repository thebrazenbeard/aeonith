# Optional exact-source location audit

Aeonith's v1 critic validates that a provider's short quotation occurs in the
submitted text, but does not identify *which* occurrence of a repeated phrase
is intended. `aeonith.evidence` supplies a deterministic, read-only sidecar.

```python
from aeonith.evidence import audit_review_spans, locate_quote

print(locate_quote("Sea, sea.", "sea"))  # exact-case second occurrence only
# For a completed critique from an explicitly configured provider:
# locations = audit_review_spans(work_text, completed_result)
```

The sidecar leaves `aeonith.review.v1` output unchanged and uses a distinct
`aeonith.quote_locations.v1` schema. Each textual anchor includes every
overlapping match's count; at most 16 candidate spans are included by default
(configurable up to 32). Spans are half-open indexes into the unmodified
Python string, measured in Unicode code points rather than bytes or grapheme
clusters. Duplicate matches are flagged `ambiguous`; none is chosen by fiat.
There is no case-folding, whitespace repair, fuzzy retrieval, or Unicode
normalization. A missing quote is rejected when auditing a purportedly
completed review.

`source_text_sha256` helps associate an audit with one exact manuscript
revision; this is a content fingerprint, **not** a proof of ownership, time,
identity, consent, or integrity of a remote transcript. Do not publish the
fingerprint or quotations from a private manuscript without the author's
permission. The sidecar performs no I/O, stores no text, and never invokes a
model or external service.

User-supplied external evidence references have no manuscript offsets and are
always labeled `provided_unverified` here. Finding a quotation in a work
proves only literal occurrence, not literary interpretation, historical
context, formal verification, author intent, or an appropriate revision.

## Qualification evidence

- Exact Unicode and overlapping matches, capped count behavior and ambiguity:
  `tests/test_evidence.py`.
- Fail-closed behavior on malformed source references and non-completed review:
  `tests/test_evidence.py`.
- Real collaboration with the public `critique()` contract via an injected
  local fixture provider: `tests/test_evidence.py`.

No paid provider call, original-GPT comparison, or human literary-quality
evaluation is implied by these checks.
