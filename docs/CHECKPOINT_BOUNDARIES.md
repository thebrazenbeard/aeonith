# Checkpoint-scoped long-form review (v0.4 candidate)

A manuscript owner may mark a reading frontier with a literal token such as
`[ps]`. Aeonith can now create a **metadata-only** plan covering exactly the
prose **after** that token. No source before or including the marker is put in
an excerpt review request.

This feature is a **boundary guard**, not an LLM, a literary critic, an
automatic manuscript editor, a source of author intent, or proof that a model
will respect every instruction. The only source content exposed by the Python
request builder is the selected post-marker excerpt, when the caller explicitly
invokes it.

## Offline CLI

```shell
python -m aeonith.checkpoint --input manuscript.md --title "Draft"
python -m aeonith.checkpoint --input manuscript.md --marker "[ps]" --chunk-chars 16000 > private_plan.json
```

The CLI emits a JSON plan with full-source and eligible-excerpt SHA-256
fingerprints, exact Unicode code-point offsets, neutral numbered section labels,
and a complete coverage statement for the **eligible tail only**. It prints
**no manuscript body text** or discovered chapter headings. It does not invoke
any model, connect to a provider, or write to manuscript files. Treat its hashes
and offsets as sensitive metadata rather than publishing them by default.

If the marker is absent, duplicated, or appears after the last reviewable
content, the operation fails closed and prints a generic error to stderr. A
changed source or an altered plan cannot be used to build a request.

## Python interface

```python
from aeonith.checkpoint import plan_after_checkpoint, checkpoint_segment_request

source = "Private opening.[ps]# Canto III\nWhat happened afterward?"
plan = plan_after_checkpoint(source, title="Unpublished work")
request = checkpoint_segment_request(source, plan, 0)

assert "Private opening" not in request["work"]["text"]
assert request["work"]["text"].startswith("# Canto III")
```

The request is compatible with Aeonith's v1 `critique` contract, but **nothing
is sent anywhere** until a separate caller selects an explicit provider and
invokes `critique`. If a provider is used, the caller remains responsible for
owner permission, privacy, context/cost limitations, and selecting an allowed
endpoint. A marker by itself is not consent for disclosure.

## Editorial limitations

- This mode deliberately withholds all previous chapters from the model.
  It cannot validate continuity against unseen earlier material and must not
  claim to have read the whole book.
- The exact post-marker region may still contain future plot revelations.
  **Do not include them in an author-facing critique** if the author requests
  blind feedback. The application handling review output must separately
  enforce spoiler redaction and the author's reveal authority.
- The current checkpoint mechanism is exact, literal, and case-sensitive. A
  second `[ps]`, even inside a quotation, is rejected rather than guessed at.
- An opt-in batch runner now executes individual planned provider calls but
  cannot infer cross-chapter contradictions, apply revisions, or produce a
  validated whole-book synthesis. See BOOK_REVIEW_BATCH.md.
- There is no claim of original GPT literary parity or live provider
  qualification from these deterministic tests.

## Validation

`tests/test_checkpoint.py` exercises an exact source-to-tail round trip,
absence/duplication, Unicode offsets, corrupt metadata, stale source digests,
invalid segment indices, and metadata-only CLI behavior. Run:

```shell
python -m unittest discover -s tests -p test_checkpoint.py -v
python -m unittest discover -s tests -v
```
