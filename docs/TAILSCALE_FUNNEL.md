# Aeonith with Tailscale Funnel — optional public HTTPS

This is an **opt-in, $0-additional-service-cost** publishing path for an Aeonith instance on a computer the operator already owns. It does **not** make the local model public directly, download model weights, create cloud inference accounts, or authorize paid hosting. The basic local-only deployment remains the default.

**Public means public:** Anyone on the internet can open the Funnel URL, including attackers. Tailscale Funnel supplies HTTPS ingress, **not visitor authentication**. Aeonith still requires authorization by bearer token or a browser session created with that token before reading a manuscript or requesting a review. Do not publish a personal manuscript, a token, or a local KoboldCpp endpoint.

## Mandatory $0 and readiness checks

1. Confirm the actual Tailscale account is on the **$0 Personal plan** and the proposed use is **noncommercial**, as permitted by [Tailscale pricing](https://tailscale.com/pricing). Funnel is available on all plans, but an Enterprise trial, billing enrollment, or any paid plan does **not** meet this project's $0 rule. Stop if free-plan eligibility cannot be established; do not accept a trial or add payment information. Do **not** assume a free open-source Community plan applies: Aeonith currently has no published OSI license.
2. Use an existing Windows/Linux host with Tailscale installed and authenticated. Check `tailscale version` (1.38.3+), `tailscale status`, and `tailscale funnel status`. Funnel requires MagicDNS, HTTPS certificates, and permission to use Funnel in the tailnet policy. Its CLI may prompt an authorized owner to enable these prerequisites; do not change unrelated tailnet access rules.
3. Confirm Aeonith itself has passed its current source security tests and that a **locally installed**, licensed GGUF model is already running via KoboldCpp or a compatible runner. Neither a healthy web page nor a passing mock test proves real-model criticism.
4. Obtain the **actual** Tailscale device HTTPS name from your own Tailscale status/configuration. The examples below use `https://machine.tailnet.ts.net` as a placeholder. Never guess or hard-code another user's domain.
5. Verify that no other Funnel/Serve listener is using the intended public port 443. Avoid modifying an unrelated existing listener.

Official references: [Funnel overview](https://tailscale.com/docs/features/tailscale-funnel), [Funnel CLI](https://tailscale.com/docs/reference/tailscale-cli/funnel), and [free Personal plan](https://tailscale.com/pricing).

## Run Aeonith and a local model on the same computer

On an existing Windows computer running an already-installed Ollama model,
the [DPAPI-backed start and stop scripts](../scripts/README.md) automate the
private token and local server process without downloading software or
touching Funnel configuration. Supply the *verified* device HTTPS origin
when starting so the app can accept that exact public host. The manual
examples below remain available for KoboldCpp and other local runners.

Start your existing KoboldCpp/GGUF model with the API bound to loopback at `http://127.0.0.1:5001/v1/chat/completions`. **Do not expose that model port through Funnel.**

An already-installed **Ollama** runtime is another local-only option. Check
`ollama list` and its loopback listener first, then substitute
`http://127.0.0.1:11434/v1/chat/completions` for the provider URL and the
exact installed model name for `AEONITH_PROVIDER_MODEL`. Do **not** expose
port 11434 or download a model just to satisfy a deployment checklist.
OpenAI-compatible transport alone does not qualify a model: a full Aeonith
review must still finish within the configured 50-second maximum and pass
the strict evidence/schema checks. A generic text response is insufficient.

In PowerShell, set process-local Aeonith configuration. Generate a new secret; never commit or paste its value into a log or chat:

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$env:AEONITH_SERVICE_TOKEN = [Convert]::ToBase64String($bytes)
$env:AEONITH_PROVIDER_KIND = 'local-openai-compatible'
$env:AEONITH_PROVIDER_URL = 'http://127.0.0.1:5001/v1/chat/completions'
$env:AEONITH_PROVIDER_MODEL = 'local'
$env:AEONITH_ENABLE_LIVE_REVIEWS = 'true'
$env:AEONITH_FUNNEL_ORIGIN = 'https://machine.tailnet.ts.net'
Remove-Item Env:AEONITH_PROVIDER_API_KEY -ErrorAction SilentlyContinue
python -m aeonith.local_server --host 127.0.0.1 --port 8765
```

Replace `machine.tailnet.ts.net` with **the exact public Funnel hostname that belongs to that computer**. The public-origin setting is an explicit allowlist, **not** a general remote-access switch. A missing or invalid value must leave the service localhost-only. Keep the local listener on `127.0.0.1`; never bind it to `0.0.0.0`, your LAN address, or a Tailscale `100.x` address.

For a POSIX shell, equivalent configuration can use:

```bash
export AEONITH_SERVICE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AEONITH_PROVIDER_KIND=local-openai-compatible
export AEONITH_PROVIDER_URL=http://127.0.0.1:5001/v1/chat/completions
export AEONITH_PROVIDER_MODEL=local
export AEONITH_ENABLE_LIVE_REVIEWS=true
export AEONITH_FUNNEL_ORIGIN=https://machine.tailnet.ts.net
unset AEONITH_PROVIDER_API_KEY
python3 -m aeonith.local_server --host 127.0.0.1 --port 8765
```

The service token is still the root credential. Enter it once into the public editor and choose the optional browser-session control to receive an HTTPS-only, `HttpOnly`, `SameSite=Strict`, signed cookie valid for at most seven days. Further reviews from that browser can use the cookie without retyping the bearer token. The session holds **no plaintext service token** and incurs **no additional charge**. Signing out removes that browser's cookie; a stolen copy remains valid until expiry or service-token rotation. An explicit `Authorization: Bearer ...` header continues to work for command-line clients. Anonymous visitors receive only the editor and health information. The app has no public account signup, multi-user identity system, or persisted manuscripts. Treat it as **single-owner access over a public transport**, not a hardened multi-tenant SaaS.

On the owner-controlled Windows host, the DPAPI-backed launcher can put the existing token on the clipboard without creating a new token or restarting the service. Run this as the **same signed-in Windows account** that launched Aeonith, then paste into the browser's session sign-in field and clear clipboard history:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Vera\aeonith\scripts\start-aeonith-windows.ps1" -FunnelOrigin "https://vn1.tail86ea75.ts.net" -CopyTokenToClipboard
```

The path and origin above are specific to this deployment; replace them for another host. Never paste the secret into a chat, URL, README, log, or shared screenshot.

## Publish over Funnel only after local checks pass

In a separate terminal on the same host, verify the Tailscale version and current Funnel state first:

```text
tailscale version
tailscale status
tailscale funnel status
```

If the existing account and security checks qualify, expose only Aeonith's **local web port**:

```text
tailscale funnel --bg --https=443 http://127.0.0.1:8765
tailscale funnel status --json
```

The externally exposed port is HTTPS **443**, the only port this Aeonith origin configuration is intended to allow. Internally the reverse proxy targets `127.0.0.1:8765`; KoboldCpp remains separately on `127.0.0.1:5001`. Tailscale generates/uses its `.ts.net` certificate. The `--bg` configuration **persists** until disabled, including across host restarts; it is not automatically removed when you close your terminal. Funnel has bandwidth limitations and allows public HTTPS listeners only on ports 443, 8443, and 10000, but using 8443/10000 would require a separate exact-origin design review. DNS propagation can take up to ten minutes after enablement. Do not add a paid tunnel or cloud proxy to work around those limits.

## Verify the actual public route

Use a device or network **outside the tailnet** after Funnel reports an HTTPS URL. Record the exact source SHA, host, Funnel URL, and Tailscale version without recording the secret:

1. Fetch `https://machine.tailnet.ts.net/healthz` and `/`. Expect valid HTTPS, an Aeonith health payload, and the real editor assets. **Neither response proves model readiness or quality.**
2. Submit an unauthenticated synthetic `POST /api/review` with `Origin: https://machine.tailnet.ts.net` matching the actual public hostname. Expect **401** and no model invocation; body text must not appear in the error or logs. A public POST lacking `Origin` should be refused **403** before reaching the review handler. Browsers automatically include the same-origin POST `Origin`; a command-line client must set it explicitly:

   ```bash
   curl -i -X POST 'https://machine.tailnet.ts.net/api/review' \
     -H 'Origin: https://machine.tailnet.ts.net' \
     -H 'Content-Type: application/json' \
     --data '{"schema_version":"aeonith.review.v1","work":{"text":"A blue leaf fell."}}'
   ```

   This probe carries **no bearer token**, uses invented text, and must not reach the model. Replace both placeholder hostname occurrences with the host's real Tailscale DNS name.
3. Repeat with a deliberately wrong bearer. Expect the same denial. Test an unrelated `Host` or browser `Origin` is denied. Do not bypass these checks by blindly trusting `X-Forwarded-Host`, `X-Forwarded-Proto`, or any other caller-controlled header.
4. With the operator's fresh token, submit a **harmless invented excerpt** through the HTTPS web editor, after confirming the local model is actually running. Require a valid complete review, exact selected lenses, source-exact quotations, and no manuscript leak in application errors. If model output is invalid, record a failed/unverified model qualification; do not report success from an HTTP 200 health check.
5. Check that unauthenticated request bursts, excessive parallel reviews, oversized bodies, and unknown routes are bounded and leave KoboldCpp unreachable directly from the internet. Verify no paid provider URL or API key can be selected.
6. Turn off the listener as a rollback rehearsal (below), confirm the external URL stops serving, and re-enable it **only** after the checks and owner approval.

Exact HTTP `Host`/`Origin` behavior through Tailscale's reverse proxy is not documented as a stable contract here; it **must** be observed with the actual client/host before marking deployment verified. A passing unit test simulating Funnel request headers is not equivalent.

## Stop sharing and recover

To disable only the chosen public HTTPS listener (without deleting unrelated Funnel configuration):

```text
tailscale funnel --https=443 off
tailscale funnel status
```

Tailscale 1.102.4 on the verified Windows host explicitly printed this
targeted `--https=443 off` command; it was used successfully without
affecting another listener. Run `tailscale funnel --help` on the actual
host first because the CLI syntax has changed across Tailscale versions.

Also stop Aeonith with `Ctrl+C` or the host's explicit process-service controls. To disable just AI calls, set `AEONITH_ENABLE_LIVE_REVIEWS=false` and restart Aeonith. If the bearer token may have leaked, generate a new one and restart the local service; do not log the token during rotation.

**Do not run `tailscale funnel reset` casually:** it clears all Funnel configuration and could interrupt other user services. Never unregister the host, switch accounts, disable Tailscale security, or accept a paid plan as part of Aeonith troubleshooting.

## Privacy and limits

- Funnel creates a publicly discoverable HTTPS entry point. It is not access control; anyone can reach the anonymous routes, and the application must enforce review authorization.
- HTTPS protects the external transport, but the host, browser extensions, system backups, KoboldCpp and its logs can still access submitted text. The operator is responsible for their settings.
- Aeonith still has no multi-user identity, durable global request ledger, account recovery, cloud SLA, or guarantee that a local GGUF produces correct literary criticism. Per-process request limiting protects a single server process, not a distributed fleet.
- Keep Tailscale and the host patched. If your current Tailscale account isn't eligible for a genuine $0 plan, **do not deploy by this route**.

See [local-service setup](SERVICE_DEPLOYMENT.md) and [release gates](RELEASE_GATES.md) for the baseline.
