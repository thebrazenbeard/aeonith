# Training file-I/O observation: falsification tool only

**Status: OBSERVATION_ONLY — does not authorize a model optimizer.**

`PythonTrainerIOObservation(expected_private_root)` can be placed around one
trusted, disposable Python training invocation by an engineer who already has
the exact required model, permitted corpus and host resources. It records
bounded *counts* of CPython audit events for file opens-for-write and common
filesystem mutations, grouped by whether the path is lexically inside the
expected output root. It does not record filenames, raw paths, training text,
model outputs or exception messages.
For rename and hardlink operations, the destination determines the primary
`lexical_scope_counts`, while the source appears separately in
`source_operand_scope_counts`. A symlink event classifies its new link name,
not the referent text. Relative paths used with `dir_fd` are classified as
`unknown_dirfd_relative`; they cannot safely be resolved against process cwd.

Example integration for an already-qualified *synthetic* callback:

```python
from experimental.trainer_io_audit import PythonTrainerIOObservation

with PythonTrainerIOObservation("/isolated/native-linux-private-root") as audit:
    # Invoke an independently approved synthetic test callback here.
    pass
sanitized = audit.receipt()
assert sanitized["trainer_output_custody_qualified"] is False
```

The tests demonstrate a genuine falsifier: an `os.write` to an already-open
descriptor **produced zero observed events while changing a file outside**
the expected root. A separate symlink-redirection test writes physically
outside the root while recording the opening path as *lexically inside*.
Additional tests verify that rename and hardlink destinations outside the
root are visible even when their sources are inside, and that directory-fd
relative writes are reported as unknown rather than falsely cwd-scoped.
A malicious library, native extension, path replacement or subprocess may
evade this instrument. Even a clean observation cannot
clear the existing `training.train_lora._require_private_output_broker` gate.

## Why `save_strategy="no"` is insufficient

The current Aeonith `SFTConfig` sets `save_strategy="no"`, `logging_strategy="no"`
and `report_to="none"`. Those are Trainer behavior configurations; they do
**not** authenticate the initial output directory, prove that imports and
extensions avoid file I/O, or constrain arbitrary callbacks. The official
TRL stand-alone SFT script even calls `trainer.save_model(output_dir)` after
training; Aeonith uses the class directly, so the stand-alone script is an
illustration of a possible write path, **not proof Aeonith calls that script**.

- [Transformers TrainingArguments source](https://github.com/huggingface/transformers/blob/main/src/transformers/training_args.py)
- [TRL stand-alone SFT script](https://github.com/huggingface/trl/blob/main/trl/scripts/sft.py)
- [CPython audit-hook security limitations](https://docs.python.org/3/library/sys.html#sys.addaudithook)

## Remaining real qualifications

The repository specifies `transformers >= 5.2` but does not pin a complete
Transformers/TRL/PEFT/safetensors build. The optional ML packages are **not
installed in this test environment**; the six tests below exercise synthetic
CPython filesystem activity, not a genuine `SFTTrainer` execution. A later
probe must record the resolved package versions and hashes, exact
`SFTTrainer` code path, and all child/native file effects before drawing
runtime-specific conclusions.

1. Bind an exact publisher-authenticated local safetensors checkpoint and
   rights-admitted training/dev/holdout corpus to an owner-authorized process.
2. Run the exact installed Transformers, TRL and PEFT versions in an OS-level
   isolated process on an authorized host, with a truly pinned private output
   boundary. Audit *actual* file operations including native and child writes.
3. Serialize the final PEFT state and config to bounded in-memory bytes,
   persist them only through verified pinned handles, and reload them into a
   **fresh** process. Independently compare trainable tensor deltas and
   validation/holdout controls. Do not equate a fresh adapter file with a
   genuine trained model or literary improvement.

The path-free final adapter serialization is *source-supported but not
verified here*: official PEFT documents `get_peft_model_state_dict(model)`;
`safetensors.torch.save(tensors)` returns bytes for dense contiguous tensors.
That still leaves PEFT-version-compatible adapter key names, config JSON,
bounded serialization memory, metadata/format expectations, atomic broker
commit, and exact fresh-process PEFT reload/inference unqualified.

- [PEFT state-dict integration API](https://huggingface.co/docs/peft/package_reference/functional)
- [Safetensors in-memory serialization API](https://huggingface.co/docs/safetensors/api/torch)

No model weights or private examples are supplied or touched by this source
experiment. It is not an installer, sandbox, telemetry service or a hidden
training invocation.
