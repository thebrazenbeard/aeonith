# Private PEFT LoRA → GGUF handoff (source-only)

Aeonith's inference preference is **local GGUF + KoboldCpp** (or llama.cpp).
The source-only `training.export_gguf` utility checks that a locally supplied
PEFT adapter, exact base files, training receipt, expected-file manifest and
local llama.cpp converter script match their supplied SHA-256 values. It can
write a private **unexecuted conversion recipe**. **It does not run conversion,
create a GGUF, download weights, or qualify a deployed Aeonith model.**

## Why the extra boundary

- A PEFT `.safetensors` adapter is not itself a GGUF or a standalone model.
- A LoRA GGUF must be used with the **matching base GGUF**, same original
  architecture/tokenizer lineage. The matching base GGUF is separately
  acquired and verified; this utility deliberately does not choose one.
- The original `training_receipt.json` identifies a claimed gradient update,
  but does not authenticate the upstream model or the training data's rights.
- `training.verify_base` compares actual local base bytes to an operator-supplied
  file list; neither that expected manifest nor a manually entered converter
  SHA-256 establishes who issued them. Both origins need independent custody.
- Compatibility of Qwen3.5 text-tower adapters with the **exact** llama.cpp
  converter revision and KoboldCpp's GGUF LoRA path is unverified until tested.

The current mainline [llama.cpp LoRA converter](https://github.com/ggml-org/llama.cpp/blob/master/convert_lora_to_gguf.py)
accepts a local `--base` config/tokenizer path, an output file, and a PEFT LoRA
directory. The converter has a Hub fallback when base files are omitted, so
Aeonith's recipe **always supplies `--base`** and offline environment flags.
The [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
documents `--lora FNAME`; [KoboldCpp's flags](https://github.com/LostRuins/koboldcpp.net/blob/main/src/content/docs/docs/reference/flags.mdoc)
also document a GGUF LoRA option. Those are interface possibilities, not
proof this exact Aeonith adapter loads or performs correctly.

## Read-only local preflight

You first need **all five existing private artifacts**, with the converter
script separately copied from a reviewed, pinned llama.cpp commit and its SHA
obtained from a trustworthy source:

1. Official Qwen3.5 Transformers base directory, with config, tokenizer,
   chat template and actual `.safetensors` files (not merely a GGUF).
2. PEFT `adapter/` holding `adapter_config.json` and `adapter_model.safetensors`.
3. `training_receipt.json` from an actually observed training step.
4. `aeonith.expected_base_files.v1` manifest from separate custody.
5. Local `convert_lora_to_gguf.py` with a separately obtained expected SHA-256.

Run without creating a file:

```bash
python -m training.export_gguf \
  --base /private/qwen-base \
  --adapter /private/training-run/adapter \
  --receipt /private/training-run/training_receipt.json \
  --base-manifest /private/qwen-base-expected.json \
  --converter /private/llama.cpp/convert_lora_to_gguf.py \
  --converter-sha256 <64-lowercase-hex-digest>
```

It verifies two separate local manifests' base/model/revision agreement,
current file hashes, PEFT config, converter content and local path boundaries.
The printed receipt excludes private paths and literary material.

To produce a **private, not-yet-executed** command plan instead, supply
`--prepare --output /private/new-handoff-dir`. The new output directory must
not exist, and will hold only `handoff_plan.json`, with a locally scoped
`conversion_argv_not_executed`, offline environment, and file hash references.
Private plans contain exact private model and adapter paths. On POSIX, the
directory and plan are created exclusively through Aeonith's descriptor-pinned
private-output writer (`0700` directory, `0600` file); symlinked ancestry and
**all Git checkouts**, including unrelated repositories, linked worktrees and
bare repositories, are rejected. An operator must still secure the output host
against other processes running under the same user and avoid untrusted writable
mounts. On Windows, **all private plan creation fails closed**, including Python
3.13+, until an independently verified DACL and handle-relative anti-reparse
writer is available. Read-only handoff inspection remains available on Windows.
No `.gguf` is created by `--prepare`; **there is no conversion execution flag**.
Review this plan and the exact converter revision before manually performing
any real conversion outside this source-only tool. Do not put full model
weights, adapters, unapproved corpora, or private handoff plans in Git.

## Qualification still required after a real conversion

1. Verify GGUF bytes and matching base GGUF lineage, tokenizer and model
   loading on an isolated authorized Windows/Linux inference host.
2. Test the base unchanged and with the adapter using the same prompts and
   decoding settings; record exact model/runtime identities.
3. Check quotation fidelity, structured `aeonith.review.v1` output, and
   genuine withheld cases over multiple seeds and human reviewers.
4. Complete separate corpus/model artifact licensing and consent review before
   publishing any adapter, merged weights or GGUF.

Even a successful external converter exit or matching hash is **not** proof
of literary-quality improvement or permission to release a model.
