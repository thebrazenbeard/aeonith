# Windows private-output experiment: FALSIFICATION ONLY

Status: **NOT_QUALIFIED**. No production Windows private writes are enabled.

The existing `aeonith/private_output.py` refuses Windows. That is currently
correct. This experiment cannot be imported or called by the runtime, and the
CLI is no-op by default. It uses no network, no models, and no user material.

## Research question

Can an ordinary, non-elevated Windows process obtain a private-output contract
with equivalent guarantees to Aeonith's POSIX pinned-parent implementation,
despite untrusted ancestor junctions and mutable parent DACLs?

Result: **UNKNOWN**. These experiments search for falsifiers; they do not
establish an adequate contract for production. A matching owner and apparently
restricted DACL at one moment cannot establish who may rename ancestors,
replace junctions, or modify a descriptor later. The test compares open handle
file identity after a deterministic parent-name replacement. That can falsify
naive claims about `FILE_FLAG_OPEN_REPARSE_POINT` protecting every ancestor.

## Opt-in procedure

Only on a Windows host which is currently available for a disposable probe,
from the repo checkout (no administrator rights requested):

```powershell
py -m experimental.windows_private_output_probe
py -m experimental.windows_private_output_probe --run-disposable-temp-probes
$env:AEONITH_WINDOWS_PROBE_OPT_IN = '1'
py -m unittest tests.test_windows_private_output_probe -v
Remove-Item Env:\AEONITH_WINDOWS_PROBE_OPT_IN
```

The default command produces `NOT_RUN_OPT_IN_REQUIRED`. Opted-in probes create
only synthetic marker files and reparse links in a freshly allocated OS temp
directory, then delete that directory. The CLI attempts junction creation with
the absolute system-directory `cmd.exe` returned by Win32
`GetSystemDirectoryW`, using `/d /c mklink /J`, a disposable current working
directory, and a shell-metacharacter-free path allowlist. It never searches
`PATH`, the caller's working directory, or `COMSPEC` for an executable. A
location whose path contains unsupported characters yields
`INCONCLUSIVE`. Directory symlinks may require Windows Developer Mode or a
specific privilege; failure is `INCONCLUSIVE`, never a success.

The script checks a temporary parent owner against the token user SID,
`GetSecurityInfo` DACL presence and protection, and, after renaming that parent,
whether `CreateFileW(...FILE_FLAG_OPEN_REPARSE_POINT)` opens a marker through an
ancestor junction/symlink. It checks both the returned path and *handle file
identity*. It prints **no host path, SID, file content, or security token**.

Even a fully executed run remains `NOT_QUALIFIED`: no private file was written
and no access boundary was promised. Error results are sanitized; a Windows
failure, including a child-process timeout, is reason to investigate, not
proof of safety. No security descriptor
is altered, and no privileged call is required.

## Adversarial matrix

| Threat | Test / observation | If hostile | Still unproven |
|---|---|---|---|
| Different directory owner | `GetSecurityInfo` owner vs token `TokenUser` SID | `noncaller_owner` | Caller-owned ancestor can still be manipulated by other authorized principals |
| Missing/null DACL | `GetSecurityInfo`, descriptor control | `absent_dacl`, `null_dacl` | Effective rights of individual ACEs, deny precedence, inherited/object ACEs |
| Inherited mutable DACL | `SE_DACL_PROTECTED` bit | `inherited_dacl` | Protected DACL still doesn't prove denied read/write/delete to all adversaries |
| Reparse/junction | `GetFileAttributesW` final parent component | `reparse_point_present` | Ancestors and object manager aliases may redirect independently |
| Parent rename before open | Rename observed parent, replace its name with junction; compare `CreateFileW` target file identity | `ancestor_reparse_traversed` | Concurrent attackers and atomic path-pinning semantics |
| Missing tools/privileges | Nonzero Windows API or junction/symlink failure | `INCONCLUSIVE` | No effect claimed |

## Primary references

- [Microsoft: CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [Microsoft: Reparse Point Operations](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-operations)
- [Microsoft: GetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [Microsoft: GetSystemDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemdirectoryw)
- [Microsoft: GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
- [Microsoft: OBJECT_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes)
- [Microsoft: NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)

**Documentation gap:** The general OBJECT_ATTRIBUTES documentation mentions
`OBJ_DONT_REPARSE`, but the user-mode NtCreateFile documentation says its
Attributes may be zero or `OBJ_CASE_INSENSITIVE`. Neither a POSIX-equivalent
user-mode contract nor access control under malicious parent-rename races can
be assumed from these sources. No default implementation should be changed.

## Actual qualification gates (none satisfied by this experiment)

1. Peer-reviewed Windows-native handle-relative, fail-closed create and write
   primitive with no path-based fallback and defined reparse-point behavior.
2. A complete, independently measured effective DACL/owner and ancestor custody
   policy, including local users, Administrators, SID aliases, deny ACEs and
   adversarial descriptor mutation; no reliance on POSIX `chmod` analogies.
3. Repeated hostile Windows host tests exercising live concurrent parent
   replacement/junction and write races, with exact OS/Python/version evidence.
4. A separate production design and independent review; no promotion of this
   `experimental/` source based on green Linux CI.
