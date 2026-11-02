# Aeonith local model recipe (not trained weights)

`models/aeonith-critic/` contains a versioned **Ollama Modelfile recipe** and
manifest. It can create a locally named `aeonith-critic:0.1` from the existing
`qwen2.5-coder:1.5b-instruct-q3_K_M` model. It requires **$0 additional
spending** and never invokes a download command or an external model service.
The installer refuses to proceed if that base tag is not already present in
the *local* Ollama inventory. A successful creation is not fine-tuning,
proprietary model-weight recovery, or literary-quality qualification.

The base is selectable **without changing the checked-in recipe**. Use
`--base EXISTING_LOCAL_OLLAMA_TAG` to point at another model already in the
local Ollama inventory. A temporary Modelfile replaces only the `FROM` line
and is removed after creation. Do not use a URL or GGUF path as the override.
The receipt records the selected base name and its actual local digest.

The package deliberately includes **no `SYSTEM` instruction**. Aeonith already
sends `aeonith.core.PROVIDER_INSTRUCTIONS`, per-lens methods, and the selected
manuscript as separate request-time instructions/data. The Modelfile only fixes
limited context, decoding parameters, and the base tag. This avoids a second
potentially conflicting system prompt.

## Creation and readback

With an existing local Ollama service on `127.0.0.1:11434`, run from this
repository using Python 3.11+:

```bash
python scripts/create-aeonith-model.py --check
python scripts/create-aeonith-model.py --create
# Or, when a different compatible base is already installed:
python scripts/create-aeonith-model.py --check --base granite-literary:local
python scripts/create-aeonith-model.py --create --base granite-literary:local
ollama show --modelfile aeonith-critic:0.1
```

`--check` performs local inventory and recipe validation only. `--create`
requires an exact installed base-model tag and 64-character local digest,
refuses to overwrite an existing target tag, creates via `ollama create`, then
reads back the derived model's digest and `num_ctx`, `temperature`, and
`num_predict` parameters. The JSON terminal receipt records its actual local
base and derived digests, recipe-manifest fingerprint, and effective Modelfile
fingerprint, but no manuscript or
credential. Save a receipt in a private, owner-controlled location if needed.
Cooperating Aeonith creators use an exclusive per-model temporary lock; a
stale lock after a crash requires operator inspection. External Ollama clients
do not honor this lock, so a simultaneous manual `ollama create` can still
race or replace the target. Keep model creation serialized on the host.

The installer forces its CLI subprocess to the numeric loopback endpoint,
clears inherited proxy and cloud-key variables, and sets Ollama's no-cloud
option. It does not use Tailscale Funnel, alter an existing Aeonith process,
install Ollama, or attempt `ollama pull`. Local Ollama daemon behavior and
runner trust still require host review. If the base is removed between
preflight and creation, stop and inspect instead of assuming no daemon-side
download occurred.

If the tag already exists, the command stops without modifying it. Do not
delete or replace an existing model merely to get a successful installer exit.

The Windows launcher offers an **opt-in Aeonith critic profile**, matching the
one locally observed successful structural pilot (schema-constrained JSON,
2,048 output tokens, one lens). It does not silently alter legacy defaults,
fine-tune weights, or guarantee critique quality or a 50-second response.
The named model must already exist in local Ollama inventory. Test only with
original, non-sensitive text:

```powershell
.\scripts\start-aeonith-windows.ps1 -Profile aeonith-critic
```

The critic profile requests only five minutes of Ollama model residency;
legacy profiles retain 24 hours. Even five minutes can consume several GiB
of host RAM/VRAM. Inspect shared workloads before starting a model. During
the 2026-11-02 pilot, WorkBridge owned the default Aeonith port 8765 on
Lappy. Choose a *verified free* higher port rather than stopping that service,
for example:

```powershell
.\scripts\start-aeonith-windows.ps1 -Profile aeonith-critic -Port 8766 `
  -PythonExe 'C:\path\to\installed\python.exe'
# Open http://127.0.0.1:8766/ locally only after the startup readiness message.
.\scripts\stop-aeonith-windows.ps1
```

`-PythonExe` accepts an existing absolute interpreter path on a local fixed
drive, rejecting UNC, device and mapped-network paths. The default PATH-based
Python discovery is subject to the same checks and a real Python 3.11+
preflight. This avoids relying on a broken WindowsApps alias without changing
host PATH or installed interpreters. The stop script reads the recorded port
and verifies PID, start time, executable and Aeonith command line before
terminating the owned process. An older deployment record without an explicit
profile is not adopted into the new profile; stop the old process explicitly.
The single deployment record intentionally prevents multiple concurrent
Aeonith launchers. A nondefault port is **local-only**: combining `-Port` other
than 8765 with `-FunnelOrigin` is rejected.

An existing Aeonith listener cannot change models, profiles or ports in
place. Never expose Ollama's port, retarget Funnel implicitly or publish
manuscript content for this test.

## What the receipt proves, and what it does not

- **Proves (with successful real local execution):** a locally named model was
  created and its enumerated digest and selected settings were read back.
- **Does not prove:** independently trained weights, improvement over the base,
  complete 14-lens literary analysis, provenance or license of the local
  quantized base, privacy of model-runner logs, or safe public deployment.
- **Still required:** real model-backed `aeonith.review.v1` tests against
  synthetic, permissioned writing; exact-quote and lens validation; latency
  and repeated-seed results; blinded human evaluation of depth, calibration,
  counterreadings, and comparative quality.

The manifest records the local quantization's license and provenance as
**unverified**. The named Qwen family is not proof of this tag's actual
producer, hash, or redistribution terms. Weights must not be copied to GitHub
without checking the exact local artifact's origin and legal rights.

One [sanitized Lappy runtime pilot](HOST_PILOT_20261102.md) subsequently
confirmed a real single-lens structural completion using a locally created
`aeonith-critic:0.1` based on installed `qwen3:4b-instruct`, **only** with
JSON-schema output and a 2,048-token request budget. An earlier 800-token
JSON-object attempt failed validation. This is not a quality or training pass,
and does not qualify the default Windows launcher settings.

### Candidate: Granite literary writer

One possible evaluation candidate is
[`PJRM/granite-3.3-2b-instruct-literary-writer-v0.1-Q4_0-GGUF`](https://huggingface.co/PJRM/granite-3.3-2b-instruct-literary-writer-v0.1-Q4_0-GGUF).
Its upstream [`agentlans` model](https://huggingface.co/agentlans/granite-3.3-2b-instruct-literary-writer-v0.1)
is reported to be an Apache-2.0 fine-tune of IBM Granite on a literary
*creative-writing* dataset. That is relevant prior training, **not evidence
of good critical analysis** or Aeonith-specific training. It is not known to
be installed on Lappy; the manifest does not claim it is. No download or
model replacement is authorized by merely listing the candidate. If it is
separately installed under a chosen Ollama tag, `--base` allows a controlled
comparison against the current default on identical held-out short passages.

Official references: [Ollama Modelfile](https://docs.ollama.com/modelfile),
[Ollama model inventory API](https://docs.ollama.com/api/tags), and
[Ollama model import](https://docs.ollama.com/import).
