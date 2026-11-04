# Disposable WSL user-scope resource-limit check (source-only candidate)

This is a **one-shot, opt-in source candidate** for VN1. It invokes only
stdlib Python, systemd-run, systemctl and cgroup v2 files. It does **not**
load a model, import Transformers/PyTorch, train, stress memory, change
`.wslconfig`, restart WSL, modify Aeonith/Ollama services or persist a daemon.

The reason for an executable helper is concrete: two previous ad-hoc probes
created disposable scopes but their nested PowerShell-to-WSL shell scripts lost
quotes/dollar signs. Neither measured the effective limits. This probe sends
argv directly; there is **no `sh -c`, Python `-c`, `eval` or interpolation**.

After checking WSL systemd PID1 and cgroup v2 controllers, an owner can run
it from the local verified Aeonith source checkout:

```bash
python3 -m experimental.wsl_scope_qualification --execute
```

Without `--execute`, the command refuses, and nothing is launched. With it,
the tool creates a uniquely named temporary `systemd-run --user --scope`
process, requesting 512 MiB maximum memory, 384 MiB memory-high threshold,
25% CPU, 16 tasks and zero swap. The child uses *the same source file*,
reads `/proc/self/cgroup` and the actual `memory.max`, `memory.high`,
`memory.swap.max`, `cpu.max` and `pids.max` of its own cgroup, then returns
one JSON receipt. Any missing, malformed or mismatched value is a failure.

The parent stops **only** its own randomized scope, verifies it is unloaded,
and refuses to issue success on any missing teardown evidence. On success the
receipt explicitly states `training_lease_established=false`: process-specific
limits demonstrated for a tiny test command **do not reserve RAM or confer
authority on a later, separate Qwen load or optimizer**.

This source-only code has no live host qualification claim until it actually
runs successfully against VN1 and its receipt is independently examined.
No other user-owned processes should be killed in order to make it pass.

To test without systemd or host effects:

```bash
python -m unittest tests.test_wsl_scope_qualification -q
```
