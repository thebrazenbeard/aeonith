# Path-free PEFT adapter export — bounded source experiment

The opt-in `training.peft_memory_export.export_peft_adapter_to_broker()`
prepares the **default causal-LM LoRA adapter** of an already-updated PEFT
model without asking PEFT to write a pathname. It reads
`get_peft_model_state_dict(model, adapter_name="default")`, serializes the
tensor payload with `safetensors.torch.save(...)` in memory, converts the
adapter config's Enum/set fields into JSON, and writes exactly two allowlisted
files through `PinnedTrainingArtifacts.write_adapter_bytes()` on Linux:

1. `adapter_model.safetensors` — first, mode `0600`, exclusive creation.
2. `adapter_config.json` — last, mode `0600`, exclusive creation.

Both bytestrings are complete and bounded *before* any file is created.
Configuration is limited to 64 KiB and serialized weights to the shared
private file cap (currently 64 MiB). The returned SHA-256 and byte-count
manifest is **not a training receipt**; its exact status is
`adapter_bytes_exported_not_training_qualified`.

Before reporting the export, the broker now opens both files by pinned
`dir_fd` with `O_NOFOLLOW`, rejects extra/missing entries, checks exact mode
`0600`, owner, regular-file type, single hard link, length, digest and stable
file metadata across the read. The descriptor is opened with `O_NONBLOCK`:
even if a same-UID adversary swaps an expected file for a FIFO, readback
refuses immediately rather than hanging before `fstat`. Socket, directory
and symlink substitutions are also rejected. Its separate
`point_in_time_private_adapter_readback_not_training_qualified` receipt
proves only a bounded, immediate disk readback. An interrupted two-file
export has no completed receipt and remains private for manual inspection;
the API does not erase it or accept incomplete outputs. There is still no
atomic bundle commit, crash-recovery transaction, immutable artifact custody,
publisher-authenticated provenance or fresh-process PEFT reload proof.

### Actual verification

`python -m unittest tests.test_peft_memory_export -v` tests six synthetic
boundary cases using fake PEFT and Safetensors modules: no external ML
packages are needed, and no model or user corpus is loaded. A real parent
rename/symlink substitution cannot redirect the pinned writer on the test
Linux filesystem. Invalid configs, absent modules, empty state, oversize
payloads, and duplicate exports fail without overwriting private bytes.

**Not qualified:** Neither the actual PEFT implementation nor its current
`adapter_config.json` compatibility was exercised in this environment.
Model tensor CPU copies and in-memory Safetensors buffers may exceed the
64 MiB disk cap in peak RAM. A crash between two file creations leaves an
incomplete private bundle; there is no atomic commit marker, no rollback,
and no fresh-process PEFT reload proof. The caller remains responsible for
authentic base weights, admitted and protected training input, gradient
update evidence, host resources and explicit authority.

The two existing trainers still use pathname-oriented TRL runtime output
and `model.save_pretrained`. Their execution gates have **not** been lifted.
Do not wire this serializer into either trainer until their remaining
path-based writes and process behavior are independently qualified.

Primary API references:

- [PEFT low-level adapter state dict](https://github.com/huggingface/peft/blob/main/docs/source/developer_guides/low_level_api.md)
- [PEFT adapter config and save behavior](https://github.com/huggingface/peft/blob/main/src/peft/config.py)
- [Safetensors in-memory Torch serializer](https://github.com/huggingface/safetensors/blob/main/bindings/python/py_src/safetensors/torch.py)
