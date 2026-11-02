# Aeonith local-model pilot (structural qualification only)

This is an executable, bounded **$0 additional-spending** pilot for an already
installed local model runner. It exercises the real `aeonith.critique()` path,
the `LocalOpenAICompatibleProvider`, and the separate structural auditor. It
cannot download, train, modify or redistribute model weights. It never selects
a paid cloud provider or forwards a manuscript to a remote endpoint.

The pilot uses three tiny, newly authored, harmless source passages stored in
`evaluation/model_pilot.py`. They are public diagnostic fixtures, **not** a
genuinely unseen evaluation set or a measurement of generalization. A default
run reviews just one passage through one `symbolic` lens, minimizing context
and output pressure on small local models. The runner's model identifier and
chat endpoint must be explicit or accepted as the loopback default; only
numeric `127.0.0.1` or `[::1]` chat-completions URLs are allowed. No API keys.

## Run from a source checkout

Start a local model server separately, with its HTTP listener bound to the
same machine's loopback interface. Verify the model license, actual free
resources, server logging and local API model ID before running. For example,
KoboldCpp commonly exposes a compatible route on port 5001:

```bash
python -m evaluation.model_pilot \
  --model local \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --lens symbolic \
  --repeats 3 \
  --output pilot-results.json
```

The output file must not already exist. On POSIX, it is created with mode
`0600`; on Windows, review the directory's ACL. Without `--output`, the same
sanitized JSON prints to standard output. The default model timeout is 120
seconds per attempt and maximum output is 2,048 tokens. Change these with
`--timeout` and `--max-tokens` if the model warrants it. Use `--structured-outputs`
only if the local runner supports JSON Schema; otherwise JSON-object mode is
requested. `--case unanswered-bell` selects the second passage; `--all-cases`
tests all three and multiplies the number of attempts by the repeat count.
Use `--lens NAME` multiple times for distinct selected lenses, but start with
one on modest hardware. See `--help` for accepted canonical names.

This command **does not start or install a model server**. If one is absent,
every attempt should be recorded as `provider_error`, not a fabricated review.
Exit status `0` means all attempted responses passed Aeonith's **structural**
audit; `1` means at least one attempt failed; `2` means a CLI/configuration
error. An unsupported remote endpoint is rejected before an HTTP request.

## Report contract and limits

The report's `aeonith.local_model_pilot.v1` fields include:

- `model_identifier_sha256`: fingerprint of the caller-declared model ID, not
  proof which weights a process used.
- `summary`: attempted, completed, structurally passing, structurally failing,
  and provider/model-failing counts. **Every attempted invocation counts.**
- `attempts`: bundled case ID and text hash, repeat index, elapsed seconds,
  bounded status, structural-audit result, audit warning/violation codes, and
  a per-selected-lens `basis`, literal work-quote count and limitation count.
- `semantic_quality: UNASSESSED` and `human_evaluation: NOT_PERFORMED` in every
  report, including reports with 100% structural success.

The report contains **no manuscript, generated critique, quotations, full
provider response, HTTP URL, plaintext model ID, bearer token, or exception
message**. The CLI cannot accept arbitrary private manuscript files. The
underlying model process may nevertheless see the three fixture passages and
could log them; inspect and configure the runner accordingly. Text hashes and
model-ID hashes are linkable fingerprints, not confidentiality guarantees.
The report is a local execution observation, not authenticated attestation of
model weights, source revision, host identity or literary merit. Preserve the
exact Git head and runtime/model checksum separately if making provenance
claims; avoid publishing private host paths or credential material.

## What makes a model useful?

This is only the first engineering gate: can a local model return complete,
well-formed, quote-grounded answers for selected lenses repeatedly? It cannot
determine whether a plausible quote **supports the interpretation**. Any
claim of improved literary judgment needs separately held-out consented works,
human review across genres, disclosure of failed outputs, and blinded,
order-swapped comparisons against a controlled baseline. The existing
`evaluation/quality_eval.py` human-study workflow supports that later stage.
Do not include the pilot's public sample texts in a supposedly unseen holdout.

## Tests

```bash
python -m unittest discover -s tests -p 'test_model_pilot.py' -v
```

These use fake providers only, include simulated fabricated quotes and
failures, and make **no real model calls**. A passing test suite does not
qualify an actual local provider.
