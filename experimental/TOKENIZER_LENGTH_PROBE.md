# Offline, tokenizer-only synthetic candidate length probe

This **source-only experiment** determines whether the pinned Qwen3.5-0.8B
chat template can encode the current 42-row synthetic literary *proposal*
without truncation, and whether each assistant completion starts at the exact
generation-prompt token boundary. It is not a model load or a training step.

## Run on an explicitly approved local host

Requires an already downloaded and hash-pinned base directory and an existing
local Python environment with `transformers`; this command installs nothing,
does not contact Hugging Face, does not write a candidate file, and does not
load any `.safetensors` weights:

```bash
python -m experimental.tokenizer_length_probe \
  --base-dir /absolute/local/path/to/verified/qwen3.5-0.8b/base \
  --max-length 4096 \
  --execute
```

Without `--execute`, it refuses and does **not import Transformers**. With
`--execute`, it checks pinned SHA-256 digests and byte lengths for the six
required tokenizer/config files against the repository manifest, loads only
the local fast tokenizer with `trust_remote_code=False`, measures all 42
synthetic in-memory rows, and rehashes the tokenizer assets afterward.
`--max-length` must be an integer from 128 through 4096; a single overflow,
invalid token ID, missing completion, or non-prefix-stable chat template
refuses the **whole** receipt. No truncation or partial pass is permitted.

The exact prompt and compact JSON completion strings mirror the candidate
mapping in `training/admit_candidates.py`. Token masks follow
`training/cpu_step_candidate.py`: prompt prefix labels are `-100`, and only
assistant completion tokens are loss-bearing. The resulting receipt contains
per-row index/split/numeric token lengths, masked prompt token count,
supervised completion token count, aggregate counts, per-split token-length
ranges, candidate SHA-256 and explicit nonqualification flags; **no manuscript,
example text, prompt, completion, host path, local username or source ID** is printed.

The probe intentionally does **not**:

- grant corpus admission, authorship, editorial approval or data-steward rights;
- authenticate model publisher origin or establish protected loader custody;
- open model weights, instantiate a model, run a forward pass or an optimizer;
- establish useful learning, literary quality, hidden evaluation custody,
  adapter persistence or permission to train.

All of those are separate gates. A pinned digest proves agreement with the
repository's expectation, **not** independent publisher authentication.
The load between before/after hash checks is not descriptor-pinned and cannot
defeat a malicious same-UID race. Use a trusted host-owned read-only snapshot
for stronger custody; this script does not claim it has established one.

## Test locally without ML dependencies

```bash
python -m unittest tests.test_tokenizer_length_probe -q
```

Tests use a deterministic fake tokenizer and adversarial inputs; they do not
require downloaded weights, model runtimes or corpus approval. Real successful
token lengths require executing the above command on the authorized host with
the genuine pinned tokenizer. An offline probe failure must be reported as a
failed measurement, never converted into an inferred pass.
