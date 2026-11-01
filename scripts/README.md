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
```

Replace the example with the **actual** Tailscale device DNS name. The script
verifies the selected Ollama model already exists locally, connects to its
**loopback-only** 11434 API, limits reviews to one lens, and runs the Aeonith
HTTP listener only on `127.0.0.1:8765`. If you already have a service on
8765, it stops without touching it.

On first start, a fresh cryptographically random bearer token is encrypted
with Windows **per-user DPAPI** to
`%LOCALAPPDATA%\Aeonith\token.dpapi`. The launcher never prints it.
It also preloads the existing Ollama model and keeps roughly 1 GiB of
model RAM reserved for 24 hours, preventing the usual five-minute idle
unload from causing a cold-inference timeout. This makes no paid calls or
downloads. After 24 idle hours, reviews may again be slower.
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

The current tiny Ollama model was **qualified only for one symbolic lens**
with a harmless sample. The browser selects that one lens by default.
Other lens combinations are not yet
qualified to produce complete valid reviews within 50 seconds.

To stop only the recorded Aeonith process:

```powershell
.\scripts\stop-aeonith-windows.ps1
```

The stop script verifies the stored PID, start time, executable path, and
command-line identity before terminating anything. It does **not** stop
Ollama, unload the resident model, modify Tailscale, or remove the DPAPI token. If public Funnel was
enabled, disable its exact Aeonith listener separately **before** stopping
the local server; do not use a broad `tailscale funnel reset`.

Neither script creates a scheduled task or Windows service; after a reboot
the owner must start Aeonith again. See
[`docs/TAILSCALE_FUNNEL.md`](../docs/TAILSCALE_FUNNEL.md) for public-port
prerequisites, external test requirements, and targeted rollback.
