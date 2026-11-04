# Bounded provider-opt-in long-form review batches

Aeonith can execute a set of excerpt reviews against an explicitly injected
provider using a canonical exact-source plan. This is not a whole-book
synthesized judgment, automatic cross-chapter retrieval or autonomous service.

This Python API is separate from the single-excerpt browser. On the current
Windows/Ollama host, model compatibility must be qualified for the chosen
segment size and lens count before using the runner on private writing.

## Local-only command

The installed `aeonith-book` command (or `python -m aeonith.book_cli` from
the checkout) accepts a named local UTF-8 text/Markdown file or an explicitly
selected, narrowly supported `.docx` file and writes a
**new**, private JSON report outside any Git checkout. It never overwrites an existing output path,
prints manuscript text, runs a paid provider, or selects an external endpoint.
No model is contacted unless `--provider local-openai-compatible` is supplied.

```shell
python -m aeonith.book_cli --input book.md --output ../private-review.json \
  --provider local-openai-compatible \
  --url http://127.0.0.1:5001/v1/chat/completions --model local \
  --lens symbolic --chunk-chars 2000 --max-segments 32 \
  --max-output-tokens 2048 --call-timeout-seconds 45 \
  --max-total-seconds 600
```

For a Word `.docx` manuscript, supply `--input-format docx --input book.docx`
with the same private output and local provider settings. This is opt-in and
uses only Python's standard library; it does not upload the original document
to a conversion service. Input must be a local `.docx` ZIP no larger than
16 MB, with no more than 256 parts, 64 MB aggregate expanded data, and a
32 MB per-part ceiling. The extracted UTF-8 text must fit the existing
2-million-character/8-MB source limits. The importer preserves text from
ordinary paragraphs, including table-cell paragraphs, tabs and line breaks;
it discards Word formatting and table layout. It **refuses** comments,
footnotes/endnotes, headers/footers, tracked/hidden text, drawing and
embedded/media parts, legacy binary `.doc`, macro documents, XML entities and
markup-compatibility wrappers that could conceal Word-ignored text, and other
content that cannot be represented safely as this plain-text subset.
These refusals protect against silently skipping meaningful writing. **Exact
source coverage in the segment plan means the extracted text, not every part
of the original Word package or its visual layout.** Export unsupported Word
documents locally to reviewed UTF-8 text before using this runner; inspect
the export for missing content before sending it to a model.

The local runner must already be installed and permitted to process the
writing. The command defaults to **one symbolic lens**, 2,000 source
characters per excerpt, eight maximum segments, 2,048 output tokens per
request, 45-second individual timeouts, and a 180-second overall timeout.
All limits are operator-selectable within hard bounds. Plans exceeding
`--max-segments` are refused **before any model request**. The overall
deadline is enforced when each local call begins and by constraining that
call's socket timeout; it is not an OS-level kill switch for a hung model
process. The server and model runner may independently retain logs.

For prose strictly after a unique author checkpoint, add
`--after-marker '[ps]'`. The full original source is fingerprinted for
staleness detection, but preceding prose and the marker never enter model
requests or returned segment reports.

Exit status 0 means every individual excerpt returned a structurally valid
critique; 2 indicates invalid input/output/configuration or a file error;
3 means no provider was selected; 4 means an incomplete provider batch;
5 means a structurally invalid local model response interrupted the batch.
An incomplete batch retains honest attempted/completed counts. The report
contains potentially sensitive quotes and review text; secure it accordingly.
The CLI rejects output paths inside a Git repository to reduce accidental
publication of private manuscript excerpts. Choose an explicit outside-repo
private directory, not a path you intend to stage or push.
On POSIX, the new output is created with mode `0600`; on Windows, actual
file access additionally depends on the user's filesystem ACLs.

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
