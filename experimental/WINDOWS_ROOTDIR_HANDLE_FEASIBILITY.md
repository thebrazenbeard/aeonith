# Windows root-directory-handle creation: disposable feasibility probe

Status: **NOT_QUALIFIED**. The production `aeonith.private_output` Windows
file-writer denial remains unchanged.

The previous source- and Windows-host-verified probe found that ordinary
`CreateFileW(... FILE_FLAG_OPEN_REPARSE_POINT)` traversed a replacement
**ancestor** junction and symlink. This experiment asks a smaller question:
does `NtCreateFile` with a pre-opened filesystem-directory handle in
`OBJECT_ATTRIBUTES.RootDirectory` keep an exclusive synthetic child creation
inside that directory after the same Windows identity renames its former path
and puts a junction/symlink at the old name?

The module `experimental.windows_rootdir_probe` is never imported by
production and never changes permissions, installed services, user manuscripts,
or real model artifacts. The default CLI is inert:

```powershell
python -E -B -S -m experimental.windows_rootdir_probe
```

A [sanitized Windows-host receipt](receipts/2026-11-03-windows-rootdir-pinned-create.json)
records two **executed synthetic cases** on one authorized Python 3.13.15
Windows host. For both ancestor-junction and ancestor-symlink replacements,
the RootDirectory-relative marker was created in the original pinned
directory (not the decoy). Both the directory handle's identity and the
cleanup readback agreed. This is a narrow host behavior observation,
**not** evidence of a private DACL or a production-ready Windows writer.

To execute with the operator's current permission on a Windows host that has
no conflicting workload, from an exact pinned source checkout:

```powershell
python -E -B -S -m experimental.windows_rootdir_probe --run-disposable-temp-probes
```

Only a fresh OS `TemporaryDirectory` is mutated. The two cases create marker
names under `parent`, pin its `CreateFileW` directory handle, rename it to
`moved`, replace `parent` with a synthetic junction or symlink, and attempt a
relative `NtCreateFile(FILE_CREATE)` under the original handle. The receipt
contains only booleans and status values, never paths, SIDs, or file content.
An unsupported API/privilege returns `INCONCLUSIVE`. Even both cases reporting
anchoring success cannot satisfy production safety.

## Separate threat boundaries

1. **Path ambiguity:** A rooted handle should exclude the *formerly named*
   ancestor from the child create. But the initial handle itself was opened by
   a path and is **not** verified against a trusted identity/ancestor chain.
2. **Other Windows principals:** No effective DACL/owner/ACE evaluation is
   implemented. A protected DACL, a matching owner, and a temporary success
   are not an access-control guarantee. The test does not assess concurrent
   DACL mutation, SID aliases, Administrators, hard links, or network shares.
3. **Same-SID malicious process:** This test deliberately performs the ancestor
   swap as the *same* user. Same-identity processes commonly share access to
   a user's files and credential material. A root handle does not create an
   independent security principal or defend against an attacker controlling
   the caller itself. A separate low-privilege OS identity/broker may be needed.
4. **Platform guarantees:** Native `NtCreateFile` is version-sensitive.
   Source tests cannot establish support for all Windows builds or filesystem
   drivers. No `OBJ_DONT_REPARSE` promise or safe fallback is assumed here.
5. **Output durability:** This is a single empty marker create, not a bounded
   private writer, verified `WriteFile` sequence, fsync, secure close,
   recovery protocol, or crash/cleanup test.

If any desired guarantee is unknown, `NOT_QUALIFIED` remains the only allowed
decision. Never wire this experiment directly into production private output.

## Primary sources

- [Microsoft `NtCreateFile`](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile): `RootDirectory` relative names and `FILE_OPEN_REPARSE_POINT` behavior.
- [Microsoft `OBJECT_ATTRIBUTES`](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wudfwdm/ns-wudfwdm-_object_attributes): `RootDirectory`, `OBJ_DONT_REPARSE`, and ambiguity of user-mode API support.
- [Microsoft reparse-point operations](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-operations): why path flags alone are insufficient to prove ancestor custody.
