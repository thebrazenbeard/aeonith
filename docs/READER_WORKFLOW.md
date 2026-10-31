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

## Explicit model call

Review the chosen provider's privacy/retention terms before disclosing a
manuscript. Set its key using your normal secret-management process; never
place credential values in command arguments or manuscripts.

```bash
export AEONITH_PROVIDER_URL="https://api.openai.com/v1/responses"
export AEONITH_PROVIDER_MODEL="SELECTED_COMPATIBLE_MODEL"
# AEONITH_PROVIDER_API_KEY is provided securely if required.

python -m aeonith.workflow --input draft.md --title "Draft" \
  --provider openai-responses --allow-external-disclosure \
  --output critique.md
```

This is an **example, not a verified live API qualification**. The disclosure
flag is only an explicit local acknowledgment. It does **not** authenticate
the user, verify consent ownership, pin the resolved network endpoint,
guarantee provider confidentiality, meter token/cost spending, or grant Rezon,
CCB or any other ecosystem authority. Those controls require an independently
secured host and remain out of scope.

For compatible Chat Completions endpoints, select
`--provider openai-compatible`. Flags
`--token-field max_completion_tokens --omit-temperature --json-mode` are available only
when the selected model documents support. These request-shape options do not
guarantee schema-conforming or useful literary output.
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
  a pre-existing file prevents a potentially billable call.
- `--api-key-env NAME` changes the environment variable read by the selected
  provider, never the secret itself.

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

The 15 local tests cover unavailable-provider honesty, external disclosure
gating (including URL environment variables), successful fake Chat and
Responses adapters, focused lenses, malformed UTF-8/title, safe exclusive file
outputs, and sanitized provider exceptions. These **do not** prove real model
interoperability, literary quality, API costs, privacy compliance, or host
authorization.
