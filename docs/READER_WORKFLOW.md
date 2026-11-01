# Aeonith one-command manuscript workflow

This optional wrapper turns a UTF-8 `.txt` or `.md` manuscript into Aeonith's
existing `aeonith.review.v1` request, invokes an **explicitly selected** model
provider, and renders Markdown or JSON in one command. It does not alter the
literary review schema, attach GPT knowledge files, perform web research, or
install an authenticated host capability.

## Offline default

```bash
python -m aeonith.workflow --input draft.md --title "Draft"
```

Without `--provider`, no model or network is invoked. The output clearly
states that no literary critique was generated, and the process exits with
code `3`. Setting ambient URL/model/key environment variables alone never
activates model inference.

## Explicit, no-cost local model call

Use a local text model already available on hardware you own (for example
KoboldCpp with a permitted GGUF). No paid provider or API key is needed;
the hard additional-service spending limit is **$0.00**. Check the local
runner's logging and manuscript handling before using private writing.

```bash
export AEONITH_PROVIDER_URL="http://127.0.0.1:5001/v1/chat/completions"
export AEONITH_PROVIDER_MODEL="local"
unset AEONITH_PROVIDER_API_KEY

python -m aeonith.workflow --input draft.md --title "Draft" \
  --provider local-openai-compatible \
  --output critique.md
```

This is an **example, not a verified local model qualification**. It fails
honestly if the local runner is unavailable or returns unusable output. The
local-only adapter constrains the destination to loopback but does not verify
manuscript ownership, confidentiality of other local processes, or permission
to modify Rezon, CCB or other ecosystem state.

For compatible **local** Chat Completions endpoints, select
`--provider local-openai-compatible`. The CLI requests JSON mode by default;
use `--no-json-mode` if your local server rejects that format. This does not
remove the requirement that the model actually generate a valid review JSON
object. No request-shape option guarantees schema-conforming or useful output.
For models explicitly supporting strict JSON Schema responses,
`--structured-outputs` opts into the same schema mode as the lower-level
review CLI; Aeonith still validates source quotes and requested lenses.

## Useful options

- `--input -` reads UTF-8 manuscript data from stdin.
- `--lens symbolic --lens stylistic` selects only those lenses instead of
  defaulting to all fourteen; duplicate or unknown lens names are rejected.
- `--format json` preserves the machine-readable v1 review result.
- `--output -` writes to stdout (the default). A named output path is
  exclusively created with mode `0600` on POSIX systems; existing files
  are never overwritten. The path is reserved before provider invocation so
  no attempted local generation happens if the output already exists.

The input converter rejects invalid UTF-8, NUL characters, empty or oversized
work, and requests larger than the existing JSON CLI limit. The Markdown
renderer escapes potentially misleading model text and labels interpretation
and references as unverified. Model failures preserve the existing exit codes:
`3` unavailable, `4` provider error, `5` invalid provider output.

Output files may contain private manuscript quotations and provider-generated
interpretations. Store them accordingly. If an unexpected local write failure
occurs after file reservation, an empty or partial owner-readable file may
remain; the tool never silently overwrites a prior file.

## Tests and qualification

```bash
python -m unittest discover -s tests -p 'test_workflow.py' -v
```

The local tests cover unavailable-provider honesty, loopback-only routing,
focused lenses, malformed input, safe exclusive file outputs, and sanitized
provider exceptions. They **do not** prove actual local model
interoperability, literary quality, local runner confidentiality, or host
authorization.
