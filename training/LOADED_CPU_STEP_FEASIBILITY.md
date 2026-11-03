# Experimental in-memory CPU LoRA step — not admitted for training

`training.cpu_step_candidate.experimental_loaded_cpu_lora_step` replaces the
Trainer's *direct path-based checkpointing* in one narrow prototype. It accepts
an already loaded Qwen3.5 text-tower PEFT model, in-memory train/validation
records, a tokenizer and a live `PinnedTrainingArtifacts` broker. It uses
PyTorch `AdamW` in-process for at most eight CPU-only steps, masks the entire
user prompt in the causal loss, rejects truncation and unstable chat templates,
compares trainable LoRA tensor fingerprints before/after, performs finite
validation-loss checks, and passes adapter bytes to the descriptor-pinned
serializer. There is no holdout argument in the API, but it cannot prove the
caller did not mix holdout-derived material into the train/dev rows. Its JSON receipt
contains scalar counts/losses and hashes from the adapter sink—not prompts.

This is **an experimental source primitive, not a training CLI**. Direct calls
to the public function unconditionally refuse execution **before any optimizer
or model action**. It is intentionally **not wired into `training.train_lora
train`**, whose separate output-broker gate also stays closed. Only synthetic
tests mock the refusal while using fake Torch-like objects to inspect the
otherwise unreachable orchestration. No actual Qwen weights, PyTorch, PEFT or
Safetensors were available for those tests. They do **not** establish real
autograd, finite nonzero target gradients, checkpoint compatibility, private
Trainer I/O, or fresh-process adapter reload. A changed tensor fingerprint
alone can reflect optimizer weight decay or unrelated modification, not
causal learning from the desired loss.

## What still fails qualification

1. **Input:** The caller must prove a separately approved exact train/dev
   dataset and construct it from one host-owned pinned immutable snapshot.
   Current corpus admission and experimental input reader are not wired into
   this candidate. A Python list alone is not evidence of rights or custody.
2. **Base:** A trusted host must pin the official publisher revision and
   checkpoint bytes through loading. Hashing a mutable directory, or checking
   an operator-supplied manifest, does not prevent same-user file replacement.
3. **Runtime:** Verify PyTorch/Transformers/PEFT compatibility on the host,
   prove that model/tokenizer forward/backward/autograd does not write files,
   enforce a CPU/RAM lease and resource limit, and kill/revoke the isolated
   worker without touching unrelated projects.
4. **Output:** Qualify both in-memory Safetensors serialization and broker
   output end-to-end with real PEFT, including partial-write recovery and a
   successful fresh-process adapter reload against the exact base.
5. **Evidence:** Record the real loss and changed tensors under a host-owned
   receipt, then compare blind withheld-work/seed controls. An optimizer step
   is not proof of literary improvement.

Current result: **SOURCE_TESTED_CANDIDATE / REAL_TRAINING_NOT_QUALIFIED**.
Do not use it to lift either existing training gate or advertise an adapter.
