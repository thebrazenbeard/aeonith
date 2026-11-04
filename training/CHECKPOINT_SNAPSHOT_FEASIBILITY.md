# Native-Linux checkpoint snapshot experiment (NOT training-qualified)

`training.checkpoint_snapshot.materialize_verified_snapshot` is a source-only,
explicitly invoked test of a smaller checkpoint-custody boundary. It does not
run Transformers, PEFT, a trainer, or a model optimizer. The existing CPU and
CUDA training gates remain closed.

The old offline `verify_checkpoint` hashes files reached through an ordinary
directory path. A different object can be substituted between hashing and the
later `from_pretrained(path)` reopen; matching hashes from an earlier check do
not prove which weights the model actually loaded.

This experiment instead:

1. Checks a separately supplied exact-file SHA-256 manifest, model ID,
   revision, size budget, config/tokenizer coverage, and safetensors shards.
2. Opens the Linux source directory by walking no-follow directory handles,
   rejecting Git checkouts, unqualified mounts (including WSL 9p/DrvFS),
   group/other-writable source directories and non-regular entries.
3. Opens each model file relative to the pinned directory, verifies regular
   type/owner/single-link/non-world-writable identity and expected size, then
   streams its exact FD bytes into a newly created owner-private pinned output
   directory (0700) with exclusive owner-only file creation.
4. Rechecks expected SHA-256 and source file identity after the copy, fsyncs,
   makes the copied files 0400, and independently hashes the destination FD
   readback. It validates Qwen3.5 configuration and shard-index names and
   refuses a detected source/output lexical-root substitution.
5. Returns only a content-free receipt with the copied counts and explicit
   `publisher_origin_authenticated=false`,
   `model_loader_custody_qualified=false`, and `optimizer_authorized=false`.

Errors leave a private, potentially incomplete destination for the owner to
inspect. The operation never overwrites an existing target and never deletes
any checkpoint evidence. It may need up to the full uncompressed checkpoint
size of additional free storage; `max_total_bytes` bounds that budget.

## Synthetic evidence

Run `python -m unittest tests.test_checkpoint_snapshot -q`. Cases exercise
valid bounded copies, incorrect digests, symlink leaf/ancestor replacement,
checkpoint root replacement, extra runtime assets, source mutation during
streaming, output byte corruption, invalid Qwen architecture, Git checkout
rejection, private target preservation and rejected unqualified mounts.
The fake safetensors bytes
are **not** a loadable language model.

## Why this is not an optimizer authorization

- The manifest remains an operator-provided claim. A SHA-256 match does not
  authenticate the publisher or license provenance. Independently pin the
  official Qwen revision and full file hash list.
- Any malicious process under the *same OS user*, or privileged host process,
  may still modify or replace copied files after snapshot creation, including
  by changing the mode back to writable. Mode 0400 is accident resistance,
  not immutable host custody.
- A framework may canonicalize `/proc/self/fd/<dirfd>` or independently open
  ordinary paths. This experiment does **not** bind the actual Transformers
  loaded tensor bytes to the pinned copy. A stronger host-owned isolated
  worker with read-only filesystem/mount policy, immutable source identity,
  and measured post-load weight provenance is still required.
- Tests have not exercised any genuine 1.77 GB checkpoint, HF loader, GPU,
  local model adapter, or live host permission boundary. Source TEST is not
  a MODEL_LOAD or TRAINING runtime probe.

Use this as one bounded building block in a separately authorized host
qualification, not as an invitation to remove `_require_private_output_broker`
or `_require_host_owned_gpu_allocation`.
