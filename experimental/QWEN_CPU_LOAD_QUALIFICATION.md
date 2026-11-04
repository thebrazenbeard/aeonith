# Bounded, no-gradient Qwen3.5-0.8B CPU model-load experiment

**Source-only candidate.** No host run, trained model, adapter or optimizer
step is established by adding this file. Run only on an explicitly authorized
idle owner-controlled WSL2 host after independently reviewing the exact source.

This exercise answers one narrow question: *Can this exact local checkpoint
load as CPU float32 under a verified disposable cgroup memory limit?*

The loaded model's actual parameters must be CPU `torch.float32`. A request to
the loader for `dtype=torch.float32` is **not evidence** that the Qwen3.5 text
tower obeyed it; known Transformers releases have returned BF16 regardless.
Any such mismatch fails closed without substituting a different loader.

Source command (must not run until exact host approval):

```bash
python3 -m experimental.qwen_cpu_load_qualification \
  --base-dir /home/vera/.local/share/aeonith/pilot-qwen35-08b-20261103/base \
  --execute
```

The command requires owner-private base files, checks the pinned expected
manifest/checkpoint digests, and spawns **one** `systemd-run --user --scope`
child with no shell expansion. Before importing Transformers, the child
verifies its own cgroup v2 membership and effective controls:

The parent also refuses unless `/proc/meminfo` reports at least **6656 MiB
available** in WSL, leaving a **2 GiB reserve** beyond its 4608 MiB maximum.
A separate fresh Windows free-physical-memory and unchanged-service-PID
preflight is required of the host operator; this Linux source cannot verify
that Windows-wide reserve. The returned child receipt is independently
checked for complete exact state, model manifest, nonzero CPU float32 parameter
count, memory accounting and zero training effects.

| Limit | Value |
|---|---:|
| MemoryMax | 4608 MiB |
| MemoryHigh | 4096 MiB |
| MemorySwapMax | 0 |
| CPUQuota | 50% |
| TasksMax | 64 |
| Parent wait timeout | 120 seconds |

There is no dataset input, no forward pass, no optimizer construction and no
adapter output. The receipt contains counts, digests, cgroup limits and peak
resident cgroup memory only—no prompts, private paths, token values or weights.
The parent stops only its own randomized scope and requires independent unit
unload readback. A scope OOM, timeout, missing dependency or dtype mismatch is
a **failed experiment**, not permission to increase the cap and retry.

Even if the experiment succeeds, the result does **not** establish authorized
training resources, an independent publisher-origin attestation, a protected
same-UID-immutable model loader, training input/evaluation custody, adapter
reload, learning or generalization. No automatic execution is permitted.

Offline, dependency-free source tests:

```bash
python -m unittest tests.test_qwen_cpu_load_qualification -q
```
