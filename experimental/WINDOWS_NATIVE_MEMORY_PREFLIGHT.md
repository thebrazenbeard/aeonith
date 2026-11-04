# Windows-native memory observation: no model load and no training

`experimental.windows_native_memory_gate` is a **read-only report** for an
Aeonith Qwen3.5-0.8B model-load proposal. It is not an optimizer lease or a
qualifying host probe.

Run on the **actual Windows host** (not inside WSL):

```powershell
python -m experimental.windows_native_memory_gate --inspect
```

The command reads Windows free physical memory through
`GlobalMemoryStatusEx` and a limited process-image inventory through the
**absolute** System32 `tasklist.exe`, resolved via `GetSystemDirectoryW` to
avoid the executable search path. It does **not** launch WSL, allocate a model, use a
GPU, install packages, or change any service. It reports whether the current
Windows snapshot meets the conservative 7,168 MiB available-memory floor and
lists only selected existing model/Python process names and counts. Its exit
status is intentionally **2 even for a readable snapshot**, because no
training or load is qualified.

An observed `wsl`, `wslhost`, or `vmmem` process is merely a hint: it does not
prove a particular distro is running. Absence of those process names does not
prove WSL stopped. The program **never executes `wsl.exe`** and cannot supply
the independent Linux `MemAvailable >= 6656 MiB` evidence. The Windows host
measurement must be fresh *after* WSL starts to support the existing bounded
WSL load experiment; a healthy **pre-WSL** figure cannot substitute.

For Windows-native CPU loading, RAM alone is insufficient: an exact compatible
offline torch/Transformers/TRL/PEFT environment, private Windows artifact
writer and host-owned resource lease remain unqualified. `status` is therefore
always `HOLD_NOT_QUALIFIED` or `UNSUPPORTED_PLATFORM` on an inspection.
Unknown OS observations stay null rather than being interpreted as free or
idle. The output contains no candidate passages, model weights, credentials
or full process command lines.

Focused regression:

```bash
python -m unittest -q tests.test_windows_native_memory_gate
```
