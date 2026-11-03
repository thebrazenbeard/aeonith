# Private output boundary — source-only building block

`aeonith.private_output.create_private_directory()` provides a narrow,
exclusive **new-directory** boundary for local manuscript and model-evaluation
artifacts. It is not wired into every existing CLI and has not been qualified
on the operator's Windows machines. Do not treat its presence as proof that
Aeonith's existing report writers are private.

On POSIX/Linux, this helper:

- Walks existing path components from `/` using `O_DIRECTORY`, `O_NOFOLLOW`
  and open directory descriptors. New directory creation and file writes are
  relative to pinned descriptors, rather than trusting a pathname after a
  preflight check.
- Refuses directories inside any discoverable Git checkout, including
  worktree `.git` files, and refuses ancestors that other users can replace
  via non-sticky group/world-write permissions. Shared sticky directories
  such as `/tmp` are permitted only when their owner is root or the current
  effective user; another account owning a sticky parent could still remove
  or rename the new child directory.
- Creates a **new** per-run directory with mode `0700` and checks owner and
  permissions. Writes new regular files with `O_EXCL|O_NOFOLLOW`, mode `0600`,
  checks owner/permissions and `fsync`s the bytes. It never overwrites an
  existing report and leaves created artifacts intact on close.
- Rejects nested filenames and oversized file content; individual product
  workflows must still apply their own smaller limits, disclosure controls,
  and source-retention policies.

Example for a future migrated producer:

```python
from aeonith.private_output import create_private_directory

with create_private_directory("/home/user/private-reviews/new-run") as output:
    output.write_text("review.json", private_json)
```

## Windows status: NOT QUALIFIED, deliberately refused

On Windows the helper currently refuses creation on *all* supported Python
versions. Python 3.13 added a private-directory ACL when `os.mkdir()` receives
`mode=0o700`, but that fact by itself does not prove the existing parent's
ACL or provide an equivalent handle-relative defense against junction/reparse
path redirection. Python 3.11–3.12 lack even that directory-creation
guarantee. No caller flag or local JSON assertion can enable this helper.

Before enabling Windows, implement and independently test native ACL
inspection, secure directory creation, anti-reparse access through anchored
handles, creation/owner readback and failure recovery. Keep the existing
source-only and offline paths available while sensitive-output writers are
separately qualified.

## Integration backlog

This module cannot fix the old writers without explicit call-site migration
and UX changes, because a **new directory for every run** is part of its
contract. Candidate sites needing private raw prose/artifact storage include
`aeonith/book_cli.py`, `aeonith/workflow.py`,
`evaluation/literary_gate.py`, `evaluation/quality_eval.py`,
`evaluation/paired_model_bench.py`, and `training/admit_candidates.py`.
Do not silently replace an existing `--output FILE` interface with directory
semantics: migrate each public interface and its tests explicitly.

The helper guards against another operating-system account following broad
filesystem permissions. It does **not** isolate secrets from malicious code
running with the same account, privileged administrators, compromised storage,
or processes that can read user-owned files through other authorized routes.
