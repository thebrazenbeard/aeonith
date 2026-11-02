# Windows local Ollama launcher (optional)

These scripts require a **current, owner-controlled Windows** workstation
running Python, Tailscale (only for a separately approved Funnel), and an
**already-installed Ollama model**. They never install a model or software,
contact a paid provider, create a cloud account, enable Funnel, or configure
Windows auto-start.

From the Aeonith source checkout, in PowerShell as the account that will own
the service:

```powershell
# Local-only until the public origin and Funnel have been approved:
.\scripts\start-aeonith-windows.ps1

# Or prepare the application to accept exactly this one HTTPS Funnel host:
.\scripts\start-aeonith-windows.ps1 -FunnelOrigin 'https://machine.tailnet.ts.net'

# Opt-in Aeonith critic on an explicitly verified unoccupied local port:
.\scripts\start-aeonith-windows.ps1 -Profile aeonith-critic -Port 8766 `
  -PythonExe 'C:\path\to\installed\python.exe'
```

Replace the example with the **actual** Tailscale device DNS name. The script
verifies the selected Ollama model already exists locally, connects to its
**loopback-only** 11434 API, limits reviews to one lens, and runs the Aeonith
HTTP listener only on `127.0.0.1` (default port 8765). `-Port` allows an
explicit local high port (1024–65535) when 8765 belongs to another service.
Occupied ports fail without disturbing their owners. A nondefault port cannot
be used with `-FunnelOrigin` because a separately configured Funnel mapping
must never be silently retargeted. One owned `deployment.json` record means
only one Aeonith instance can be started by this launcher at a time.

`-Profile aeonith-critic` selects installed tag `aeonith-critic:0.1`, using
2,048 output tokens with JSON-schema structured output. One harmless
single-lens structural pilot succeeded with these settings. The legacy
profile remains default (800 tokens and JSON-object mode). Neither profile
is qualified for general literary quality or reliable multi-lens review.
`-PythonExe` can bypass WindowsApps aliases with an existing Python 3.11+
interpreter on a local fixed drive; both explicit and PATH-discovered paths
reject UNC/device and mapped network locations.

On first start, a fresh cryptographically random bearer token is encrypted
with Windows **per-user DPAPI** to
`%LOCALAPPDATA%\Aeonith\token.dpapi`. The launcher never prints it.
It also preloads the installed Ollama model. The legacy profile requests
24-hour residency; the critic profile requests five minutes to reduce
prolonged contention. Preloading can consume multiple GiB and cold requests
may exceed the application's 50-second provider timeout. Check shared
workloads before starting it. This performs no explicit download or paid call.
From the **same Windows user account**, intentionally copy the token to the
local clipboard with:

```powershell
.\scripts\start-aeonith-windows.ps1 -FunnelOrigin 'https://machine.tailnet.ts.net' -CopyTokenToClipboard
```

Paste it into Aeonith's browser token field. On the public HTTPS Funnel page,
choose **Remember this browser for 7 days** to create an `HttpOnly`,
`Secure`, `SameSite=Strict` browser session; the site then allows subsequent
reviews without retyping the root token until the session expires or the
root token is rotated. The session cookie never contains the root token.
On localhost HTTP, the root token is still required for each review.
This optional clipboard operation
temporarily exposes the token to the **local Windows clipboard**, including
any clipboard-history or sync facilities you enabled; clear clipboard
history after use. Do not paste the token into chats, terminals, logs,
screenshots, or Git.

Only one symbolic-lens response from `aeonith-critic:0.1` passed the actual
structural pilot. This is not a literary-quality result. Legacy models and
other lens combinations remain unqualified; the browser defaults to one lens.

To stop only the recorded Aeonith process:

```powershell
.\scripts\stop-aeonith-windows.ps1
```

The stop script verifies the stored PID, start time, executable path, recorded
port, and command-line identity before terminating anything. It does **not** stop
Ollama, unload the resident model, modify Tailscale, or remove the DPAPI token. If public Funnel was
enabled, disable its exact Aeonith listener separately **before** stopping
the local server; do not use a broad `tailscale funnel reset`.

Neither script creates a scheduled task or Windows service; after a reboot
the owner must start Aeonith again. See
[`docs/TAILSCALE_FUNNEL.md`](../docs/TAILSCALE_FUNNEL.md) for public-port
prerequisites, external test requirements, and targeted rollback.
