# Aeonith adapter receipt and fresh-process reload

The optional `training.verify_adapter` CLI is a **local-only verification
gate** for an adapter that has **already been trained** by
`python -m training.train_lora train --execute`. It neither creates weights
nor makes an adapter into a tested literary critic. Training remains
dependent on permissioned data and a separately qualified host.

Run commands from the Aeonith source checkout. Use the exact local
Transformers **safetensors** base, the private PEFT `adapter` directory and
the matching private `training_receipt.json`:

```bash
python -m training.verify_adapter check \
  --base /existing/private/full-base-checkpoint \
  --adapter /existing/private/training-run/adapter \
  --receipt /existing/private/training-run/training_receipt.json
```

`check` requires **no optional ML packages** and does not launch inference.
It validates the bounded JSON format, the declared positive training step
and tensor-change fields, adapter type, the SHA-256 and byte size of each
enumerated local base and adapter file, plus the declared model family and
tokenizer assets. This includes `chat_template.jinja` if fingerprinted in
the training receipt. The output contains hashes, counts and explicit limits,
but no model response or original training text. This is an integrity
comparison against a **locally supplied, unauthenticated receipt**, not
independent proof that a gradient update occurred or a model is original.

When the machine has compatible locally installed `torch`, `transformers`
and `peft` packages, the following runs one very short benign prompt first
through the unchanged base and then through the reloaded adapter, in a **new
Python process** separate from training:

```bash
python -m training.verify_adapter smoke \
  --base /existing/private/full-base-checkpoint \
  --adapter /existing/private/training-run/adapter \
  --receipt /existing/private/training-run/training_receipt.json \
  --device cpu --max-new-tokens 48 --execute \
  --output /existing/private/adapter-smoke.json
```

The output file must not exist, and it cannot be placed within the Aeonith
checkout. Omit `--output` to write only the sanitized JSON to stdout. **CPU
is the default** to avoid unexpected contention with other GPU tasks.
`--device cuda` is currently rejected even with `--execute`: a CLI switch
cannot establish a host-owned GPU allocation or safe available capacity.
GPU smoke verification requires a future host-enforced lease and measured
resource limits. CPU smoke verification still requires checking system RAM,
disk, and concurrent workloads; no checkpoint size is assumed to fit.

The smoke disables Hugging Face network access and telemetry via offline
environment settings, loads the local base with `trust_remote_code=False`
and safetensors only, then loads the **local** LoRA adapter in inference
mode. It uses greedy decoding and at most 128 new tokens. It reports only
token counts and hashes of generated token IDs, whether the two token
sequences differ, and whether the adapter loaded. It does not decode,
store, or print generated prose. A successful load makes no claim about
literary quality or about the adapter's benefit. Identical outputs do not
prove a training failure, and differing outputs do not prove improvement.

The verifier does **not** convert PEFT safetensors to GGUF, attach an adapter
to Ollama/KoboldCpp, authenticate the upstream checkpoint's immutable
revision, independently validate data rights, or run a blind study.
Those remain separate deployment and qualification gates. Do not import
or publish a trained artifact until the exact base/adapter pairing,
conversion support, licensing and withheld quality results are established.
