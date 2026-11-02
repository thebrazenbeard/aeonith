# Lappy local-model pilot — 2026-11-02

Evidence class: **RUNTIME_PROBE**, not training, human literary review, or
formal verification. Operator-directed execution through the authenticated
Lappy Executor connection; source checkout at GitHub commit
`529e5f5cfa5659e4938e93fdfa7e443ef4d0b104`. The host transcript is not
reproduced in this public repository. Only sanitized observations follow.

## Model creation

- Existing Ollama base: `qwen3:4b-instruct`.
- Observed base digest:
  `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- Command: `python scripts/create-aeonith-model.py --create --base qwen3:4b-instruct`.
- Readback status: `created_and_read_back` for `aeonith-critic:0.1`.
- Observed derived digest:
  `e63423737442de4751fb2eaa974513b2ae4920a88bdaaf11b2df3f154197400e`.
- No fine-tuning, base-weight download, or model replacement was performed.

## Two real, harmless, single-lens attempts

Both used `evaluation.model_pilot`, its bundled original `mirror-at-dusk`
passage, the numeric local Ollama Chat Completions endpoint and the one
`symbolic` lens. Neither used a private manuscript. Every attempt is counted.

| Attempt | JSON mode | Output-token budget | Wall time | Model/contract result |
| --- | --- | ---: | ---: | --- |
| 1 | JSON object | 800 | 42.461 seconds | `invalid_provider_output` |
| 2 | JSON schema | 2,048 | 34.476 seconds | `completed`; structural audit `pass` |

The second response supplied two work quotation anchors, three limitation
entries, and no structural warnings or violations. The first failed rather
than being silently retried or omitted. Sanitized reports are held outside
the public Git checkout on Lappy. The successful invocation was:

```powershell
python -m evaluation.model_pilot --model aeonith-critic:0.1 `
  --url http://127.0.0.1:11434/v1/chat/completions `
  --lens symbolic --repeats 1 --max-tokens 2048 --timeout 150 `
  --structured-outputs --output D:\VERA\Aeonith-Pilot-2-20261102.json
```

After the test, `ollama stop aeonith-critic:0.1` unloaded only this model;
the model tag persists. No Aeonith HTTP service was bound to the default
port 8765 because another owned service already occupies it. The laptop
had 32 GiB physical RAM and a 4 GiB RTX 3050; resource observations vary.

## Strict interpretation

**Confirmed:** A named local model was constructed and read back from
existing weights, and one real synthetic single-lens review passed Aeonith's
structural and exact-quote checks.

**Failed:** The 800-token JSON-object first attempt did not satisfy the
provider contract.

**Unknown:** Actual literary usefulness, interpretive truth, repeatability,
cross-seed performance, other lenses, long-form synthesis, author preference,
full model provenance/redistribution permission, and any improvement over the
unchanged base. The pilot identifies the model by tag fingerprint rather than
cryptographically authenticating runtime weights for each request.

**Not done:** Training an Aeonith-specific adapter, fresh-process adapter
reload, blinded human evaluation, public deployment, model weight upload, or
GPU training. This observation must not be promoted to any of those gates.
