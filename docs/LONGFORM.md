# Long-form source planning (optional, offline)

Aeonith v1 accepts at most 200,000 characters per review; its CLI request is
bounded to 1 MB. A single model call cannot honestly be advertised as a
book-length examination when the whole work was not processed.

The optional aeonith.longform module plans contiguous, non-overlapping
source excerpts. It **never invokes a provider**, sends text, saves a file,
retrieves missing material, or invents a whole-book synthesis.

## Python interface

    from aeonith import critique
    from aeonith.longform import plan_longform, build_segment_request

    source = "# Chapter 1\nMara returned.\n\n# Chapter 2\nNobody remembered her."
    plan = plan_longform(source, title="Original draft", max_chunk_chars=16000)
    first_request = build_segment_request(source, plan, 0)

    # No provider: explicit failure, never fabricated literary criticism.
    assert critique(first_request)["status"] == "provider_unavailable"

An explicitly configured model provider could separately process each request,
subject to manuscript-owner consent, cost budget, and provider terms.
Do not infer that a collection of fragment critiques forms a validated
whole-book assessment. Cross-chapter continuity and synthesis need a separate,
tested, context-aware process with traceable source references.

## Metadata-only command

    python -m aeonith.longform --input book.md --title "Draft" \
      --chunk-chars 16000 > plan.json

The output contains *no manuscript body text or raw chapter headings*; section
labels are neutral ordinal identifiers. Source offsets, section structure and SHA-256
fingerprints can still disclose private information. Keep a private manuscript
plan private. It is not an authorization, ownership certificate, immutable
timestamp, or semantic oracle.

## Contract and scope

- Input is strict UTF-8, with no silent Unicode normalization or BOM stripping.
- Maximum source: 2,000,000 Python Unicode code points and 8 MB UTF-8.
- Maximum 512 segments; each is at most 200,000 characters and measured
  against its actual serialized JSON request-byte limit (default 1 MB).
- Segment spans use half-open [start, end) offsets into the exact original
  Python string. Every code point belongs to exactly one segment, including
  whitespace. Source and excerpt digests bind the plan to a source revision.
- Sections come from major Markdown headings (#/##), plain Chapter, Part,
  Book, Section, Act, Prologue, and Epilogue markers. Heading text is suppressed
  in exported metadata; neutral labels retain section indices.
- Oversized sections split first at paragraph or line boundaries, then at a
  hard Unicode code-point boundary. Unreviewable whitespace-only spans are
  rejected, never discarded.
- The request builder sends only minimal v1 work/title and a fixed excerpt
  scope warning. The planner does not infer literary meaning, aggregate
  criticism, or assess whole-book significance.
- The request builder recomputes and validates the canonical plan against the
  complete supplied source before returning an excerpt. This costs extra local
  processing but prevents altered non-target metadata from being accepted.
- Unicode code points differ from bytes and grapheme clusters. A hard split
  may divide a visible grapheme; these offsets are not display-character
  counts.

## Verification

Tests in tests/test_longform.py cover exact reconstruction, chapter markers,
duplicate headings, CRLF, Unicode, BOM, JSON escaping and byte budgets,
whitespace suffixes, source tampering, unrepresentable gaps, segment limits,
and a no-provider core round trip. Run the full repository
python -m unittest discover -s tests -v suite after integration.
