# Disposable Windows output-custody matrix (not qualification)

The optional `python -m experimental.windows_custody_matrix
--run-disposable-temp-matrix` composes three **synthetic** observations:

1. **Pinned RootDirectory**: after moving a disposable directory and replacing
   its old name with a junction/symlink, `NtCreateFile` must land beneath the
   original open handle. A decoy-file write is a failure.
2. **Path and ACL observation**: the ordinary `CreateFileW` path can redirect
   across a moved ancestor; owner/DACL presence/protection are inspected as
   counterexamples, **not** as adequate effective-rights proof.
3. **Interrupted exclusive creation**: a disposable child Python process
   creates a test-only pending marker and exits without closing normally.
   The parent checks that the marker remains, a new `O_EXCL` creation refuses
   to overwrite it, and no `final-training-receipt.json` was promoted.

The command does nothing without the explicit switch, and on non-Windows
hosts it returns `NOT_RUN_NON_WINDOWS`. It creates only unique temporary
directories and inert markers; no weights, corpus, tokens, production
training directories, or installed services are involved. It does **not**
change ACLs or require elevation. The receipt deliberately omits paths and
identifiers. All outcomes carry `NOT_QUALIFIED`. The CLI deliberately exits
with status **2**, even if the diagnostic probes executed, so shell automation
cannot interpret an exit-zero as permission to train.

The `summarize_matrix` function exposes falsifiers separately from unknowns.
Owner mismatch, absent/null/inherited DACL, reparse redirection, unexpected
child exit, missing partial marker, and failed exclusive retry are explicitly
recorded as falsifiers when observed. Missing values remain unqualified.
Even when every disposable case behaves as expected, the following are still
unqualified:

- Actual rights under all relevant ACEs, groups, privileges and inherited
  permissions; owner match/protected DACL alone is not effective access proof.
- Pinned opening of the **initial** authorized ancestry before any attacker
  redirects a path, and same-SID mutations after child handoff.
- Durable flush, atomic promotion and crash consistency for the actual
  Trainer/PEFT adapter and receipt write sequence.
- A host-owned training lease, real model load, resource reserve, admitted
  corpus and optimizer authorization.

Microsoft references (official documentation):

- [Reparse-point operations](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-operations)
- [Getting information from an ACL](https://learn.microsoft.com/en-us/windows/win32/secauthz/getting-information-from-an-acl)
- [GetEffectiveRightsFromAcl limitations](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-geteffectiverightsfromacla)
- [Flushing system-buffered I/O](https://learn.microsoft.com/en-us/windows/win32/fileio/flush)

This is an evidence-gathering experiment. The production Windows writer
rejection in `aeonith.private_output` and the optimizer guards MUST remain
unchanged until a separately authorized, independently qualified implementation
exists. Do not interpret a zero exit code as permission to train or deploy.
