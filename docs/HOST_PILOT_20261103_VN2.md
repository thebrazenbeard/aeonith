# Native Linux ext4 + llama.cpp synthetic pilot — 2026-11-03

Evidence class: **RUNTIME_PROBE** by the lead's authorized host-runtime specialist. This is one local, synthetic structural trial, **not** training, semantic quality, independent human evaluation, authenticated model rights, or a Windows/WSL qualification.

## Exact source and preconditions

- Fresh disposable source checkout of Aeonith PR #20 head `96d92f845101394bb5a00bc8ba2e6bef00cc40bf`; `git status --porcelain` empty both before and after.
- VN2 was observed as Linux, with 4 logical processors, about 7.8 GiB total memory and 4.7 GiB available before the run. Existing `llama-server` PID 961 was bound to literal `127.0.0.1:11435`, with no active network sessions and low preflight CPU. The runner was **not started, reconfigured, downloaded, or restarted** for this trial.
- `/v1/models` identified a local IBM Granite 3.3 2B Instruct Q4_K_M GGUF file in a pre-existing model sandbox. The candidate model identifier is fingerprinted in the receipt; its path is intentionally omitted. This does **not** cryptographically authenticate the weights or establish their license provenance.
- The isolated report parent lived on native `ext4`, **not** a Windows DrvFS/9P mount. The writer reserved an exclusive file before inference and the report was read back with Linux owner UID 1000 and mode `0600`.

## Single attempt and result

Invocation used the exact source's `evaluation.model_pilot` from its clean checkout, with a server-provided model ID, the numeric loopback OpenAI Chat Completions endpoint, original bundled `mirror-at-dusk` case, one `symbolic` lens, `--structured-outputs`, `--max-tokens 2048`, and `--timeout 120`. The model name and private host path were not printed or committed. Only the original, nonprivate synthetic passage was submitted.

**Observed:** Exit code 0. One attempt took 79.536 seconds; `completed=1`, `structural_pass=1`, one grounded work quote, one limitation, and zero audit warnings/violations. The complete [sanitized JSON receipt](../evaluation/receipts/2026-11-03-vn2-llamacpp-native-ext4-pilot.json) contains no manuscript or model-generated prose. Post-trial readback showed the same `llama-server` PID 961 still listening only on `127.0.0.1:11435`; no service replacement occurred. The isolated temporary checkout was not a deployed Aeonith service.

## Interpretation and limits

- **SURVIVES:** This precise source revision can execute a real synthetic single-lens Aeonith structural critique against an already running local llama.cpp GGUF server, and its sanitized private report can be created owner-only on this native ext4 host.
- **UNKNOWN:** Repeatability, other lenses, long-form usefulness, actual literary interpretation, human comparative ratings, model data/weight provenance, and model training. The test is not evidence that a generic KoboldCpp runner is installed or qualified.
- **SEPARATE:** Windows production private-file writes remain fail-closed. WSL2 ext4 may be a future candidate, but WSL `/mnt/c` and `/mnt/d` can involve Windows DrvFS semantics and are not qualified by POSIX mode bits alone. No Windows Aeonith service was restarted; no WSL instance was started here.

This historical host receipt does not define product-wide requirements. See the generic [local model qualification](LIVE_PROVIDER_QUALIFICATION.md) and [KoboldCpp](KOBOLDCPP_RUNTIME_QUALIFICATION.md) runbooks for reusable guidance.
