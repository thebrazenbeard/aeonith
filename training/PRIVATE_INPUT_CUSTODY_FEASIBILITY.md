# Linux pinned private input: bounded source experiment

`training.private_input.PinnedPrivateInput` is a **source-tested read-only
primitive**, not an admitted corpus or an enabled optimizer. It accepts an
absolute, traversal-free local path outside a Git checkout, walks each
ancestor with `O_NOFOLLOW` directory descriptors, verifies the kernel mount
ID against native Linux filesystem types, then opens a regular owner-only,
single-linked file through the pinned parent descriptor. No Windows/WSL
DrvFS permission claim is made.

Example for a disposable, owner-owned `0600` test file on native ext4:

```python
from training.private_input import PinnedPrivateInput

with PinnedPrivateInput.open("/private/source/train.jsonl", max_bytes=64 * 1024 * 1024) as source:
    exact_bytes = source.read_bytes()  # private data in memory, never logs text
    fingerprint = source.fingerprint()  # sha256 and byte count only
```

The read comes from the **same opened inode**, using explicit-offset
`os.pread` rather than a shared descriptor seek position, with file size, metadata,
ownership and mount rechecked before and after reading. Synthetic tests cover
leaf/ancestor symlink refusal, rename-plus-symlink ancestor substitution,
disallowed permissions, hardlinks, concurrent content mutation and a mocked
unqualified WSL filesystem. A deterministic duplicated-descriptor test moves
the shared seek position between chunks without affecting the snapshot.
The caller is responsible for not logging raw
bytes or privately guessable fingerprints.

> **NOT_QUALIFIED for end-to-end training:** Existing
> `training.corpus.inspect_plan`, Hugging Face Trainer, PEFT and safetensors
> still use separate pathname I/O. This helper is not invoked by the enabled
> training path (which remains blocked). A clean pinned snapshot does **not**
> establish that a later process read the same bytes, that the operator owns
> the corpus, or that a same-UID/root attacker cannot mutate already-open
> files. The input descriptor needs to be retained through an explicitly
> qualified consumer, and output/host leases remain separate gates.

No model, corpus, GPU, service or outside host resource is touched by these
synthetic unit tests.
