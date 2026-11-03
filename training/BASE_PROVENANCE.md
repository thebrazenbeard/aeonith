# Offline local checkpoint fingerprint gate

`python -m training.verify_base` compares a **locally materialized** Qwen3.5
Transformers checkpoint against a separately supplied expected-file manifest.
It runs without optional ML packages, downloads, telemetry, inference or
training. It **cannot authenticate who produced the manifest** or prove that
its declared Hugging Face revision is genuine. A comparison against hashes
invented from the same untrusted local files proves little. Obtain and preserve
expected hashes through a trustworthy independent source before using them.

The supported IDs are `Qwen/Qwen3.5-0.8B`, `Qwen/Qwen3.5-2B`, and
`Qwen/Qwen3.5-4B`. Keep weight files, tokenizer, any separate chat template,
configuration, and optional sharded index together in one private directory
outside the public Aeonith repository. `.gguf` inference quantizations cannot
replace these Transformers safetensors. The verifier intentionally **rejects
symlinks**, including Hub-cache snapshot symlinks, to avoid silently hashing
outside the selected materialized directory. An operator must materialize a
controlled local copy or choose an independently controlled non-symlink
checkpoint store; the tool never copies files itself.

## Expected-file manifest

Create a separate UTF-8 JSON file outside the model directory, with the
following format. The placeholder bytes/hashes below are **not valid evidence**:

```json
{
  "schema_version": "aeonith.expected_base_files.v1",
  "upstream_model_id": "Qwen/Qwen3.5-0.8B",
  "upstream_revision": "<exact lowercase 40-character upstream Git commit>",
  "files": [
    {"name": "config.json", "bytes": 123, "sha256": "<64 lowercase hex characters>"},
    {"name": "tokenizer.json", "bytes": 123, "sha256": "<64 lowercase hex characters>"},
    {"name": "model.safetensors", "bytes": 123, "sha256": "<64 lowercase hex characters>"}
  ]
}
```

List **every runtime-affecting file present** (`*.json`, `*.jinja`,
`*.safetensors`, `*.model`, `*.txt`) with its exact byte length and SHA-256;
the example above is minimal. A tokenizer asset, `config.json`, and complete
safetensors weights are required. A sharded checkpoint requires
`model.safetensors.index.json`; each referenced shard must be present, in the
manifest and the exact set of local safetensors files. Unknown extra runtime
assets cause failure. The inspector does not parse tensor contents or test
whether the files are a valid functioning checkpoint.

For **researching** official upstream metadata, Hugging Face's
[`HfApi.model_info`](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.model_info)
accepts a pinned `revision` and `files_metadata=True`; its LFS metadata
includes object hashes for large files. A Git object hash for an ordinary
non-LFS file is **not equivalent to a SHA-256 digest of its contents**. Obtain
the correct SHA-256 for every file through a separately verified source.
Recording the upstream repository ID or a commit hash in a JSON field does
not itself authenticate that repository, publisher or hash list. No online
metadata calls are made by this verifier.

Run from the Aeonith source checkout:

```bash
python -m training.verify_base \
  --base /private/models/Qwen3.5-0.8B \
  --manifest /private/expected/qwen35-08b-expected-files.json \
  --expected-model Qwen/Qwen3.5-0.8B \
  --expected-revision <40-character-commit-sha>
```

The output is a **text-free** receipt containing the declared model/revision,
manifest SHA-256, verified file/shard counts, and explicit `false` fields for
origin authentication and host-training qualification. It does not include
local paths, weights, tokenizer bytes or manuscripts. An operator should
retain the manifest, source URL, exact remote revision, the independent
provenance chain and the receipt together as private evidence. Repeat the
check if the directory changes.

## Security and qualification limits

- The verifier rejects duplicate JSON keys, path traversal, unexpected
  checkpoint directories, local symlinks/Windows junctions, UNC paths,
  mismatched sizes/hashes, missing
  tokenizer/configuration and incomplete indexed shards.
- It is an **offline byte comparison**, not a cryptographic signature
  verification, remote publisher authentication, security scan, GPU fit test,
  model-load test, license determination or LoRA gradient-update test.
- It cannot prevent a privileged local attacker from swapping files while
  the verifier hashes them. Use a stable, trusted host-owned store when that
  race matters.
- Keep the training plan's declared model/revision aligned with this verified
  source. `training.train_lora inspect` does not consume this extra receipt.
  Actual CPU training execution now requires `--expected-base-manifest` and
  rechecks the exact local model/tokenizer bytes after the private-output
  broker and corpus-admission gates but before optional ML imports or an
  optimizer step. It also checks the plan's SHA-256 against the previously
  admitted preflight and uses that same parsed plan/model path for loading,
  preventing a later plan re-read from silently changing the selected base.
  Missing/mismatched files fail closed. This proves **local
  equality only**: a manifest created from the same untrusted local files
  is not independent evidence of official Qwen publisher provenance, and a
  shared-directory adversary can still swap model files after hashing but
  before loading. Host-owned immutable source custody remains unqualified.
- This source-only tool does **not** make the unavailable official model
  weights appear on Lappy; no model was downloaded or trained by its tests.
