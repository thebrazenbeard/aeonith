# Local training output broker — Linux feasibility probe (SOURCE ONLY)

**Disposition: PARTIAL for direct same-process and explicit trusted-child
fd-relative operations; UNKNOWN for real Transformers/TRL/PEFT training.** This prototype deliberately does not
enable `training.train_lora train --execute` or turn a test into a host lease.

`training.private_artifact_broker.PinnedTrainingArtifacts` is a small Linux-only
fixture for examining safe output custody. It uses the shared
`aeonith.private_output.create_private_directory` boundary to create a new
mode-0700, owner-verified run directory outside ordinary/bare Git checkouts.
It then creates mode-0700 `runtime` and `adapter` subdirectories through the
pinned parent descriptor, opens them with `O_DIRECTORY|O_NOFOLLOW` and retains
their descriptors. An exclusive mode-0600 receipt is written through the
pinned root handle. The broker refuses Windows and non-Linux hosts.

### Observed tests

`python -m unittest tests.test_private_training_broker -q`

- **SURVIVES (narrow):** Direct same-process writes through literal
  `/proc/self/fd/N` child paths continue to target the original directory
  after the original ancestor is renamed and replaced by a symlink.
- **SURVIVES (narrow):** Child creation, ownership, mode, bare Git denial,
  exclusive receipt and refusal after broker close.
- **SURVIVES (narrow):** The broker can now write already-serialized bytes
  for exactly `adapter_config.json` and `adapter_model.safetensors` through a
  duplicated, verified adapter directory handle. The shared private-file
  writer enforces exclusive mode-0600 creation and the 64 MB-per-file byte cap.
  A parent directory rename followed by a hostile symlink did not redirect
  these writes; duplicate/other names, oversized input, and writes after
  closure failed closed. This is **not** a PEFT encoder or genuine checkpoint
  persistence proof: bytes were synthetic, the two files are not an atomic
  bundle, and host-owned process isolation is still absent.
- **FAILS (falsifier):** A consumer first calling `Path.resolve()` on the
  procfd path receives the conventional absolute path. After ancestor rename
  and symlink substitution, a later write through that canonicalized path can
  land in the substituted destination. A real trainer may canonicalize paths.
- **FAILS (scope):** A normal subprocess does not inherit the broker's
  file-descriptor table; its `/proc/self/fd/N` lookup is not the parent
  process's directory. A trainer may fork or launch helpers.
- **SURVIVES (bounded trusted child):** A separate CPython interpreter launched
  with `subprocess.run(..., pass_fds=handoff.pass_fds)` can parse the versioned
  `TrainingChildHandoff` record, `fstat` both inherited descriptors, check
  procfs identity, owner and mode `0700`, then create a synthetic file using
  `os.open(name, ..., dir_fd=verified_fd)` under the original private output
  directory after its ancestor was renamed and replaced by a symlink.
- **FAILS CLOSED (tested child falsifiers):** No explicit fd inheritance,
  altered expected inode, a child swapping an inherited descriptor for a
  foreign directory via `dup2`, and a changed directory mode all stop before
  synthetic writes. Malformed, duplicate-key, boolean-fd and alias-fd JSON
  transport records are rejected. Child verification is an explicit required
  call; it does **not** happen automatically for arbitrary executables.
- **FAILS (lifetime):** A consumer can cache a `/proc/self/fd/N` `Path` before
  broker closure. After that descriptor closes and its integer is reused,
  the *cached* path can name a different directory. The broker refuses new
  property access after close, but it cannot revoke strings already handed
  to another component. This is reproduced deterministically with `dup2`.
- **UNKNOWN:** Whether installed Transformers, TRL, PEFT and their checkpoint
  helpers preserve literal procfd paths through every write, restart, and
  optional worker. None of these optional ML libraries is installed in the
  scratch test environment. No optimizer, artifact save, or adapter reload
  was run.

### Exact handoff boundary and limitations

While the parent `PinnedTrainingArtifacts` context is open, it may call
`handoff = broker.child_handoff()`, then pass `handoff.to_json()` to a **trusted,
specifically reviewed** subprocess and set
`pass_fds=handoff.pass_fds` on Linux. The child must call
`TrainingChildHandoff.from_json(record).verify_current_process()` *before*
using the returned descriptors, and keep those descriptors open and unchanged
while doing fd-relative output. `pass_fds` is explicit: an ordinary process
creation intentionally inherits no broker directories.

This record consists only of descriptor numbers and observed `(device, inode,
uid)` metadata. **It is not signed, a capability grant, an executable approval,
or cross-process attestation.** A malicious child can ignore validation,
alter descriptor state after checking, forge records and write through any
permissions it already has. `pass_fds` conveys directory handles to the child,
which increases the child's access to those directories by design. Do not
pass it to an untrusted program. A parent may close/reassign its descriptors
before spawn, a child may close/reassign them after validation, and cached
`/proc/self/fd/N` strings can alias recycled numbers. The root's final
human-readable path can also change via ancestor rename; descriptor identity
alone does not prove durable publishing location or correct post-run readback.

**No proof of SFTTrainer/PEFT integration follows:** they may resolve paths,
spawn workers without inherited fds, create outputs outside supplied paths,
or cache path strings after descriptors close. These real writers remain
unobserved. The new tests execute only synthetic child-file creation, not a
training checkpoint, adapter reload, restart recovery, external executable
authorization, trainer source audit or hardware lease.

### Required before lifting the real optimizer gate

1. Pin exact input corpus bytes through parsing and hashing, and retain
   audited train/dev/holdout custody. A path re-read after a separate hash
   can race with replacement. The input audit is a separate workstream.
2. Inspect exact pinned versions of every actual model/trainer/checkpoint
   writer for canonicalization, subprocess behavior, path lifetime, caches, and temporary
   paths. One successful synthetic `Path.write_text` is insufficient.
3. Qualify host-owned CPU and RAM reservations plus validated full local
   checkpoint/tokenizer provenance; this cannot be inferred from a GGUF.
4. Execute adversarial path-swap and restart tests with the full local
   training stack, including adapter save, evaluation, fresh-process reload,
   and a cryptographically tied training receipt. Preserve private incomplete
   outputs on failure for owner inspection.
5. Do not enable Windows private-file output until its separate handle,
   reparse-point and owner/DACL proof is established.

`train_lora._require_private_output_broker()` remains deliberately
fail-closed. This artifact is a tested piece of *research*, not an approved
training destination or evidence that any neural weights changed.

### Possible path-free PEFT adapter save, not yet implemented

Official PEFT exposes `get_peft_model_state_dict(model)` for adapter-only
parameters, and Safetensors exposes `safetensors.torch.save(tensors) -> bytes`.
That combination could avoid calling PEFT's pathname-oriented
`save_pretrained()` for *the two final adapter files*: serialize the verified
adapter state in memory, then supply its bounded bytes to
`write_adapter_bytes()` through the pinned descriptor. The adapter config
would require exact PEFT-compatible serialization, and a **fresh-process
reload and inference comparison** before qualification. This does not solve
the training runtime's other path writes or resource authorization.

- [Official PEFT state-dict API](https://huggingface.co/docs/peft/package_reference/peft_model)
- [Official Safetensors in-memory Torch save](https://huggingface.co/docs/safetensors/api/torch)
