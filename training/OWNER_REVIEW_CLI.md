# Private interactive review of original synthetic candidates

This optional local CLI lets the actual operator inspect every model-generated
synthetic candidate and decide whether to **admit**, **reject**, or **exclude**
that record. It is not a training command, a grant of third-party rights, or a
claim that an AI-generated critique has independent human editorial quality.

The tool works only on a qualified **native Linux filesystem** (including
private ext4, subject to host authorization). It requires a direct controlling
terminal, a private owner-only candidate file, and a new, never-used output
directory outside **all** Git checkouts. Windows and unqualified mounts are
refused. Do not put candidate files in the source checkout, OneDrive, public
web roots, a shared drive, or CI artifacts.

For an authorized operator with an existing private candidate export:

```bash
python -m training.review_candidates \
  --candidates /private/operator-space/pilot-001/candidates.json \
  --output /private/operator-space/pilot-001-owner-review
```

- The program displays each passage and proposed single-lens critique in the
  local **controlling TTY**, not standard output or standard error. The
  terminal scrollback, SSH host, screen recorder or host supervisor might
  still capture the screen. **Do not invoke this command through ChatGPT,
  Executor, an agent, a remote tool, or a session recorder when reviewing
  real candidates.** The owner must run it manually from a trusted local,
  non-logging terminal; do **not** stream or record the session. The program
  itself has no web UI, connector call, or network transfer.
  Untrusted passages and proposed critiques are displayed with terminal
  control characters and Unicode directional formatting rendered as visible
  escapes. Those display escapes do not change the reviewed file or its hash.
- Each record requires an individual `admit`, `reject`, or `exclude` choice.
  Rejections/exclusions require one of `rights_unclear`, `quality`, `duplicate`,
  `out_of_scope`, or `other`. A blank/invalid choice or `quit` stops with no
  approval output. No choices are prefilled; partial progress is not saved.
- After all records, the operator must enter their real self-attested identity,
  type the **entire displayed candidate SHA-256** and type
  `APPROVE_PRIVATE_LOCAL_TRAINING`. An incorrect value aborts. The program
  validates every choice under the existing `candidate_synthetic_admission.v2`
  contract before creating the output directory.
- Only then does it create a fresh mode-0700 private output directory with a
  mode-0600 `approval.json`. This is an *operator self-attestation*, not a
  cryptographic signature. No manuscript, candidate passage or critique is
  copied into that approval, and no adapter publication is authorized.
- To proceed further, independently inspect and admit the candidate with
  `training.admit_candidates`, separately audit and approve the exact admitted
  corpus fingerprint, and qualify host-owned trainer output custody and
  memory/resource safety. **This utility never loads a model or starts an
  optimizer.** The production training guards remain closed.

If the command fails after private output creation, treat any destination
content as **unqualified**; do not reuse it as an approval or overwrite it.
Choose a new destination after investigating the failure.
