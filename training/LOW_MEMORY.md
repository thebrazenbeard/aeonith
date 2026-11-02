# Experimental Qwen3.5-0.8B NF4 training (source-only, unqualified)

Aeonith has an **optional 4-bit adapter-training lane** at
`python -m training.train_qlora`. It is a bounded **QLoRA-style experiment**, not
a claim that Aeonith has a fine-tuned model or that 4 GiB VRAM is sufficient.
No 4-bit gradient-update, persistent adapter, reload, or held-out comparison has
been demonstrated on Lappy. Ordinary Aeonith installs do not require these ML
packages.

**Current execution gate:** The CUDA `train --execute` path intentionally
returns an error **before importing Torch, allocating GPU memory or creating
training output**. Although the NF4 training implementation and memory checks
are retained as source for future experiments, no host-owned atomic GPU lease
broker is integrated. A free-VRAM snapshot or operator flag is not an
enforceable allocation. `inspect` remains available offline. Do not treat a
passing contract test as an authorized or demonstrated optimizer run.

## Local prerequisites

- Windows with a compatible CUDA device and locally qualified Python GPU
  packages, or Linux/WSL2 with compatible NVIDIA CUDA passthrough. Never assume
  WSL is working merely because a Windows GPU is present.
- An **already downloaded** official full Transformers/safetensors checkpoint
  of `Qwen/Qwen3.5-0.8B` (not a GGUF) with tokenizer and chat template,
  stored outside the public Git checkout. An immutable 40-hex upstream revision
  is mandatory in the plan. `train --execute` additionally requires a separate
  expected-file manifest accepted by `training.verify_base` and bound to the
  same model ID/revision. Comparing local bytes against that manifest still
  **does not authenticate the manifest's issuer or upstream publisher**.
- `torch` with CUDA; compatible `transformers>=5.2`, `bitsandbytes`,
  `accelerate`, `datasets`, `peft`, `trl`, and their local dependencies.
  Versions and available NF4 kernels require actual host qualification. No
  automatic install or network download is attempted.
- A separate private `aeonith.training_plan.v1` file and private
  train/validation/holdout JSONL, with every item explicitly authorized to
  train. Adapter-publication permission may be `false`; publication remains a
  different decision. The candidate-proposal tool can create these only after
  recorded rights-holder, steward, and editorial approvals; it cannot
  authenticate those people or independently verify their claims.
- An explicit, exclusive training-resource grant from the machine's operator.
  The script's GPU memory floor is a **safety refusal threshold**, not a
  resource lease or proof that the model will fit.

## Inspect without loading a model

From the Aeonith source checkout, use private paths appropriate for the host:

```bash
python -m training.train_qlora inspect --plan /private/aeonith/training-plan.json
```

The plan/weights/tokenizer and corpus must reside outside the Git checkout.
`inspect` hashes base assets and checks corpus rights attestations, source split
isolation, pinned revision *syntax*, and the lower-memory limits below. It
returns `validated_not_trained`. It does **not** import Torch or access CUDA.

## Future explicit experiment (currently disabled)

The following interface is reserved for **after** an actual host-enforced
allocation service, rights review, compatible full checkpoint, and GPU/WSL
qualification. **It is rejected now even with `--execute`.**

```bash
python -m training.train_qlora train \
  --plan /private/aeonith/training-plan.json \
  --expected-base-manifest /private/aeonith/expected-files.json \
  --output /private/aeonith/new-qlora-run \
  --execute
```

The new output path must not exist. The runner first checks all locally
materialized model/tokenizer/configuration bytes against the separately
supplied manifest; neither its presence nor a successful comparison proves
the manifest came from the official model publisher. The runner never pushes to Hugging Face,
downloads weights, uses hosted inference, or contacts Supabase. It sets local
offline/telemetry flags before optional imports. On execute it requires CUDA
and at least 3,072 MiB *free* before loading, requests NF4 4-bit double
quantization and float16 compute on the single visible GPU, forbids the
FlashAttention-2 path (uses SDPA), and verifies actual 4-bit loading, CUDA-only
parameter placement, text-embedding dtype, and remaining free VRAM before
building an optimizer. It
requires at least 1.5 GiB remaining just after model loading and at least
1 GiB remaining **both after k-bit preparation and after inserting LoRA**.
PEFT's preparation may cast non-quantized tensors (including embeddings) to
float32, consuming substantial additional memory after a seemingly successful
4-bit load. These thresholds are refusal checks, **not** evidence that the
remaining optimizer, activations, and evaluation will fit. Because
Transformers has had four-bit loading/device-placement regressions, these
readbacks matter and can fail. The script does not use automatic CPU offload.

Its deliberately conservative *source-level* limits are **64 optimizer steps**
and **512 tokens per sample**, with completion-token loss, small rank-4
`all-linear` LoRA adapters and an 8-bit paged optimizer. It checks each
train/validation sample length without truncation, excludes holdout from the
trainer, hashes trainable tensors before/after, and requires finite train/eval
loss before saving a PEFT-format adapter and text-free receipt. A process may
still encounter CUDA OOM or OS pressure during load/training; there is no
verified 4 GiB performance guarantee or host training lease.

If a real run succeeds, `training_receipt.json` remains **private** and
explicitly carries unresolved rights, revision, reload and literary-quality
limitations. Before asserting a usable Aeonith model: check the saved PEFT
adapter with `python -m training.verify_adapter check`, independently reload
in a fresh process (`smoke --execute`), and perform multi-seed blind evaluation
against the unchanged base on genuinely unseen works. Separate licensing and
artifact review are required before publishing anything.

## Primary API sources and failure considerations

- [Hugging Face PEFT quantization guide](https://huggingface.co/docs/peft/en/developer_guides/quantization): NF4 double quantization, preparation for k-bit training, and QLoRA `all-linear` adapters.
- [Transformers bitsandbytes guide](https://huggingface.co/docs/transformers/quantization/bitsandbytes): 4-bit adapters update extra parameters, CUDA compatibility and memory measurement.
- [TRL SFT Trainer](https://huggingface.co/docs/trl/sft_trainer): prompt/completion datasets, completion-only loss and PEFT training.
- [Transformers issue #43032](https://github.com/huggingface/transformers/issues/43032): 4-bit device-placement OOM reports; a real host probe remains mandatory.
- [Transformers issue #44910](https://github.com/huggingface/transformers/issues/44910): Qwen3.5 FlashAttention-2 incompatibility reports; this lane does not request FA2.

The optional Granite 3.3 literary-writer GGUF mentioned by Patrick remains a
candidate *inference* baseline. It cannot be directly fine-tuned by this
Transformers QLoRA script and must not be silently substituted for the pinned
official Qwen3.5-0.8B training base.
