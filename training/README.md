# Optional Aeonith LoRA/SFT training lane

This directory supplies a **source-available, opt-in training path**, not a
trained model or a qualification result. It has not been run against Lappy's
real accelerator or any official full-size checkpoint. It is **not** installed
as a mandatory dependency of Aeonith's standard-library application.

The current route targets the **text tower** of the official
[`Qwen/Qwen3.5-2B`](https://huggingface.co/Qwen/Qwen3.5-2B) or
[`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B) Transformers
checkpoints. These published checkpoints are Apache-2.0 licensed. The runner
does not train from a `.gguf` inference quantization, download a model, use
cloud inference, contact Supabase, or set up any service. An adapter remains
dependent on the exact base model and tokenizer; the project cannot claim it
contains a self-contained trained model simply by committing a manifest.

## Prepare private training inputs

On the **authorized training machine**, outside the Git checkout, create a
plan JSON and three UTF-8 JSONL splits. The example below contains only the
schema shape; replace every placeholder with actual **local** paths and a
verified immutable upstream commit SHA. Do not commit private texts or local
paths to the public Aeonith repository.

```json
{
  "schema_version": "aeonith.training_plan.v1",
  "base_model": {
    "id": "Qwen/Qwen3.5-2B",
    "revision": "<40-character upstream commit sha>",
    "local_dir": "<existing local Transformers safetensors model directory>"
  },
  "corpus": {
    "train": "train.jsonl",
    "validation": "validation.jsonl",
    "holdout": "holdout.jsonl"
  },
  "training": {"max_steps": 2, "max_length": 512, "seed": 17}
}
```

Each JSONL line has this structure:

```json
{"id":"unique-1","source_id":"work-1","prompt":"A source passage and critique request you have rights to use","completion":"A grounded critical response","rights_basis":"self_authored","permission_to_train":true,"permission_to_publish_adapter":true}
```

Supported rights bases: `self_authored`, `public_domain`, `cc0`, or `licensed`.
`licensed` additionally requires `license_id` with the actual applicable
license identifier. These are **operator attestations**; string validation is
not legal verification. Keep source provenance and human-reviewed permissions
outside this machine-readable format. Do not use privately attached custom-GPT
knowledge, copyrighted literary passages, unconsented manuscript drafts, or
restricted third-party datasets without a real applicable right. An adapter
may memorize training material; publication requires a separate data audit.

The preflight rejects missing rights attestations, duplicate record IDs,
cross-split repeated prompts or `source_id`s, empty splits, remote paths,
unrecognized base-model families, missing local safetensors, and unpinned base
revision syntax. It **cannot** detect semantic paraphrase contamination,
incorrect declarations of ownership, or a local checkpoint silently differing
from the claimed upstream revision.

## Validate without any ML packages

From the source checkout:

```bash
python -m training.train_lora inspect --plan /local/private/training-plan.json
```

This does not start inference or training. It validates all three splits and
produces `validated_not_trained` metadata: split counts, SHA-256 fingerprints,
rights-basis counts, the declared upstream revision, and local base-file hashes.
No prompt, completion, source identifier, or private manuscript content is
printed. The model files are streamed for hashes, so a large local checkpoint
will make even inspection take some time.

## Attempt actual local adapter training

In an isolated environment on the authorized host, provide locally installed
compatible `torch`, `transformers >= 5.2`, `datasets`, `peft`, `trl`, and their
dependencies. The standard Aeonith install does **not** require these. Their
versions and compatibility must be qualified on the actual machine; in
particular 4 GB of VRAM does not establish that Qwen3.5-4B fine-tuning fits.

```bash
python -m training.train_lora train \
  --plan /local/private/training-plan.json \
  --output /local/private/new-aeonith-run \
  --execute
```

`--execute` is mandatory, and the new output directory must not exist or sit
inside the Git checkout. The procedure sets Hugging Face and Transformers to
offline mode, loads only an already-present local safetensors checkpoint with
`trust_remote_code=False`, and selects `AutoModelForCausalLM` to train the
Qwen3.5 **text-only** tower. It uses a small LoRA targeting `q_proj` and
`v_proj`, loss on completion tokens, an explicit training-step limit, no Hub
push, no trackers, no model downloads, and no checkpoints by default.

The command rejects records that exceed the configured token context rather
than silently truncating a completion. It checks that trainable tensors really
changed, training and validation loss are finite, and the PEFT adapter files
exist before writing `training_receipt.json`. The persisted files are
`adapter/adapter_config.json`, `adapter/adapter_model.safetensors`, and a
text-free receipt with their SHA-256 hashes, base-file hashes, corpus hashes,
local package versions and explicit limitations. Training uses **train** and
**validation** data; the holdout is read only for preflight overlap detection,
never passed to `SFTTrainer`.

**Important:** A successful training receipt proves a local gradient update,
not literary skill. Independently reload the adapter in a fresh process;
compare multiple seeds and genuinely withheld critique tasks against the
unchanged base model; assess exact quotations, usefulness, hallucination,
counterreadings and privacy with blind human review before declaring Aeonith
qualified. Never publish model/adapters or data without a license/consent
review. This lane does not automatically publish a GitHub model release.

## Why these APIs

The [Transformers Qwen3.5 implementation](https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/qwen3_5.md)
distinguishes text-only `Qwen3_5ForCausalLM` from the multimodal conditional
generation model. [TRL's Qwen3.5 regression tests](https://github.com/huggingface/trl/blob/main/tests/test_sft_trainer.py)
explicitly load the text tower through `AutoModelForCausalLM` with Transformers
5.2 or newer. [TRL's SFT documentation](https://huggingface.co/docs/trl/sft_trainer)
specifies prompt/completion datasets and PEFT integration. Earlier TRL versions
had a known [multimodal forward-method issue](https://github.com/huggingface/trl/issues/6483),
which is one reason this path deliberately uses the text-only mapping.

Patrick's alternative **Granite 3.3 2B literary-writer** candidate may be
worth comparing as a local *generation* baseline. A writer-tuned checkpoint
is not thereby qualified as an evidence-grounded *critic*. It is not silently
substituted for the explicit Qwen3.5 training contract, and its data and
redistribution rights require separate verification.

The reported CC0-1.0 [agentlans/literary-reasoning](https://huggingface.co/datasets/agentlans/literary-reasoning)
dataset is another **research candidate only**. Metadata alone does not
establish that individual examples are rights-cleared, independent, useful
critic targets, or contamination-free. Inspect its actual rows, provenance,
license chain and splits before making any use of it; this pipeline never
downloads it automatically.
