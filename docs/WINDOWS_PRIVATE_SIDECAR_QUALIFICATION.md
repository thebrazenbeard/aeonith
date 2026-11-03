# Temporary local Aeonith sidecar qualification (source candidate)

This is an optional, review-first host test. It has **not** been run on VN1 and
does not install, restart, reconfigure, or replace the existing Aeonith service
on `127.0.0.1:8765`. The script must be inspected on the exact intended Git
commit before an operator runs it. A full test suite on Linux is not a Windows
host qualification.

## Prerequisites

- A private, pristine checkout of the reviewed Aeonith commit on VN1, with its
  full 40-character SHA known. Do **not** point to the older live 8765 source
  checkout or an actively edited source tree. No modified, untracked or ignored
  files are allowed in the checkout, including local Python caches or virtual
  environments: this prevents injecting unexpected imported code.
- Windows PowerShell with `Get-NetTCPConnection` and `Get-CimInstance`; `git`,
  `python.exe`, and the service's dependencies on PATH.
- Local Ollama `127.0.0.1:11434` serving the separately installed
  `aeonith-critic:0.1` tag. This model consumes local resources; only run
  when the machine owner has granted an idle resource window.
- The reviewed service source must accept the 110-second provider timeout.
  The script checks this **before** starting a server and refuses an old
  50-second-only checkout.
- `127.0.0.1:8766` must be unused. Any listener on port 8766 aborts the
  process without replacing it. Do not use the singleton Windows service
  launcher for this test.
- The pre-existing Aeonith service must be listening on port 8765. The script
  records its listener identity before starting and requires the same identity
  afterward; it does not make an authenticated request to that service.

## After source review and explicit host authorization

From the isolated checkout, with the actual reviewed commit in place:

```powershell
.\scripts\qualify-aeonith-sidecar-windows.ps1 `
  -ExpectedHead 'REPLACE_WITH_REVIEWED_40_CHARACTER_LOWERCASE_SHA'
```

The script sets an independently generated service bearer only in process
environment memory, launches an entirely separate Python module server bound
to `127.0.0.1:8766`, and restores the caller's original environment. It does
not accept ambient Python environment overrides or site startup hooks (`-E -B
-S` interpreter flags), and requires the verified checkout as working
directory. It does
not read or write the machine-wide Aeonith deployment record, token file,
credential store, user manuscript, log files, or public tunnel configuration.
The only review body submitted is a short, synthetic mirror anecdote.

Output is a compact JSON receipt with exact Git head, liveness/smoke status,
one structural quote-support count, sidecar cleanup status, and whether the
existing 8765 listener remained unchanged. It does **not** print the bearer,
model analysis, or review text. A successful exit requires all three:

1. Synthetic authenticated review status `completed`, with at least one
   structurally validated quotation anchored to the synthetic work.
2. The launched child process exited and the sidecar port is no longer open.
3. The original 8765 listener snapshot is unchanged.

If child-process identity no longer matches the PID plus process start time,
executable path, and expected module arguments, the harness refuses to use
it for readiness or inference. Cleanup still terminates only the native process
object returned by its own `Start-Process -PassThru` call. It does not kill by
PID, which could accidentally target an unrelated process after PID recycling.
Abrupt termination of the **parent** PowerShell process cannot guarantee that
its `finally` cleanup runs. This is an ephemeral qualification script, not a
production supervisor.

Any successful structural receipt proves only the synthetic request crossed
the loopback HTTP boundary and passed the schema/evidence gates at the recorded
source head. It does **not** establish literary judgment quality, private
manuscript readiness, or service availability under concurrent workloads.
