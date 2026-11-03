# Local training output broker — Linux feasibility probe (SOURCE ONLY)

**Disposition: PARTIAL for individual same-process file operations; UNKNOWN for
real Transformers/TRL/PEFT training.** This prototype deliberately does not
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
- **FAILS (falsifier):** A consumer first calling `Path.resolve()` on the
  procfd path receives the conventional absolute path. After ancestor rename
  and symlink substitution, a later write through that canonicalized path can
  land in the substituted destination. A real trainer may canonicalize paths.
- **FAILS (scope):** A normal subprocess does not inherit the broker's
  file-descriptor table; its `/proc/self/fd/N` lookup is not the parent
  process's directory. A trainer may fork or launch helpers.
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
