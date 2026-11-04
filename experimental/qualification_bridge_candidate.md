# CPU-LoRA pilot bridge: read-only admission/base diagnosis

`python -m experimental.qualification_bridge_candidate` is an intentionally
**non-executing** entrypoint. It does not import Torch, allocate an optimizer,
load a model, create output files, call a network endpoint or ask for a host
lease. It exits with status `2` even when the optional exact evidence checks
pass. No CLI flag can enable optimizer execution.

Supply all five existing *private* evidence files together to run the current
read-only admission and checkpoint-byte checks:

```bash
python -m experimental.qualification_bridge_candidate \
  --plan /private/aeonith/plan.json \
  --audit-manifest /private/aeonith/audit-manifest.json \
  --approval /private/aeonith/approval.json \
  --admission-receipt /private/aeonith/admitted/admission_receipt.json \
  --expected-base-manifest /private/aeonith/base-files.json
```

The command emits a text-free status and, if present and internally consistent,
split counts and their SHA-256 values. It does not emit prompts, completions,
source passages, filenames, host paths, model weights or user identities. A
failed check is deliberately reported only as `evidence_refused`, without
echoing exception text that might contain private material. The output is
**not** a grant or reusable training token.

This bridge reuses the current `training.train_lora.inspect_admitted_plan`
and `verify_declared_base_checkpoint`. These compare operator-attested corpus
bytes and expected checkpoint hashes; they do not independently establish
rights, publisher authentication, trusted model loader bytes or runtime
isolation. Its fields `publisher_origin_authenticated`,
`protected_training_input_qualified`, `host_owned_cpu_lease_qualified`,
`model_loader_custody_qualified` and `private_output_and_reload_qualified`
remain false. Crucially, **neither this entrypoint nor any passed JSON result
can lift** `training.cpu_step_candidate._require_cpu_step_runtime_qualification`
or `training.train_lora._require_private_output_broker`.

For a real first step, a host-owned runtime would need a separate, independently
reviewed implementation that binds: (1) an admitted in-memory train/dev split
from immutable private input; (2) authenticated official Qwen revision bytes
through the actual Transformers loader; (3) a revocable CPU/RAM job limit and
process identity; (4) genuine Torch/PEFT behavior under traced read/write
boundaries; and (5) exclusive private adapter output, fresh-process reload,
and source-bound numerical evidence. A synthetic passing unit suite is not
such runtime qualification. The held-out split must remain inaccessible to
the optimizer.

Status: `SOURCE_TESTED_DIAGNOSTIC_ONLY`; **zero optimizer steps and zero
newly trained adapters** established by this candidate.
