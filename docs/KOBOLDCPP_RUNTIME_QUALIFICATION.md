# KoboldCpp + GGUF local runtime qualification (source-only checklist)

Aeonith's `LocalOpenAICompatibleProvider` accepts an uncredentialed, literal
numeric-loopback `/v1/chat/completions` URL, disables inherited HTTP proxies,
and refuses redirects. That source restriction **does not prove** the model
runner listens exclusively on loopback, that a GGUF file is authentic, or
that a generated literary critique is useful. This checklist does not
install KoboldCpp, download weights, start processes, or change a service.

| Gate | Evidence required | Failure / unknown interpretation |
| --- | --- | --- |
| Authorized model | Operator-owned GGUF source, license, exact digest and model identity | An arbitrary `model` field or `/v1/models` response does not authenticate the weights |
| Actual runner | Exact process/binary, version, selected GGUF and listening port | Source tests and an installed executable alone do not prove a running model |
| **Private bind** | Set KoboldCpp Network **Host** / CLI `--host 127.0.0.1`, then inspect the *actual listener* | KoboldCpp's documented default is **all interfaces**, so a successful request to `127.0.0.1` is insufficient |
| Chat compatibility | Synthetic local request with bounded output; schema, finish reason, quotes, and timeout checked | An HTTP 200 or valid JSON alone is not an Aeonith critique pass |
| Qualitative usefulness | Real blinded cross-genre human ratings with controls | Structural or automated success leaves literary quality `UNASSESSED` |

## Read-only listener checks

Run only on the **same machine as KoboldCpp** after the operator has started
their already-installed, authorized model. On Windows PowerShell:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5001 |
  Select-Object -ExpandProperty LocalAddress -Unique
```

On Linux:

```bash
ss -ltn '( sport = :5001 )'
```

The expected local listener is `127.0.0.1` (or an independently reviewed
IPv6 `::1` binding). `0.0.0.0`, `::`, a LAN address, or an unexpected
listener is **not qualified** for submitting private writing. The operating
system's live socket inventory—not Aeonith's configured *destination*—is
the relevant binding evidence. Different port selections require updating
both the listener check and Aeonith's literal loopback URL. Do not turn on
remote tunnels, firewall rules, or public forwarding to make the check pass.

## Original synthetic probe, not a manuscript

After the listener and model are independently confirmed, run the existing
Aeonith structural pilot on harmless bundled material from a separate shell:

```bash
python -m evaluation.model_pilot \
  --model local \
  --url http://127.0.0.1:5001/v1/chat/completions \
  --case mirror-at-dusk --repeats 1 --max-tokens 2048
```

This runs **real local inference** and may consume CPU/GPU time. Do not run
it during someone else's training or model job without host resource
authorization. Its default report is sanitized standard output; on Windows,
private file-writing remains intentionally fail-closed pending qualification.
The pilot reports structural completion, not a human-quality verdict. Keep
actual manuscript text out of logs, tests, public GitHub artifacts, and
synthetic qualification receipts.

## Boundaries and primary references

- [KoboldCpp official connection guidance](https://github.com/LostRuins/koboldcpp.net/blob/main/src/content/docs/docs/api/connect-apps.mdoc): OpenAI-compatible `/v1`, default port 5001; in ordinary single-model mode a model name is not a weight-provenance guarantee.
- [KoboldCpp official remote-access guidance](https://koboldcpp.net/docs/api/remote-access/): default all-interface listener and explicit Network Host / `--host` binding.
- [KoboldCpp API reference](https://github.com/LostRuins/lite.koboldai.net/blob/main/koboldcpp_api.json): `response_format` options may be converted into a grammar. Installed runner versions still require direct compatibility testing.

Aeonith's current Windows service launcher is **Ollama-specific**. Do not
restart, rebind, or replace an already-running Aeonith service to perform
this qualification. A separate, explicitly authorized private sidecar and
resource lease would be needed for a new runner live pilot.
