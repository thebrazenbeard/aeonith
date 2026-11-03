# Synthetic pilot: prepare a private, unapproved corpus-audit proposal

`training.synthetic_audit_draft` bridges the **already completed, selectively
approved** candidate export to the separate `training.corpus_admission inspect`
stage. It is a local file preparer, not an alternate approval path.

## Required prior custody and decisions

1. An exact `candidates.json` whose SHA-256 was reviewed by the real operator.
2. A separate `aeonith.candidate_synthetic_admission.v2` approval containing
   an explicit `admit`, `reject`, or `exclude` decision for **every** candidate.
3. The untouched private `train.jsonl`, `validation.jsonl`, `holdout.jsonl`,
   and `admission_receipt.json` produced by `training.admit_candidates` on a
   qualified native Linux private filesystem.
4. An **independently supplied** nonempty `aeonith.eval_exclusions.v1` file,
   whose contents were chosen by an evaluation custodian. A convenient
   fabricated exclusion ID is not evidence of a truly withheld evaluation.

The preparer revalidates the candidate and its exact v2 decisions, regenerates
the expected split bytes in memory, verifies those bytes and the admission
receipt against the private files, checks the separate exclusion format, and
builds provenance entries **only for admitted source IDs**. Rejected and
excluded records never appear as source attestations.

Run on the same qualified native Linux private host, with all files and the
output parent outside **every** Git checkout:

```bash
python -m training.synthetic_audit_draft \
  --candidates /private/pilot/candidates.json \
  --approval /private/pilot/operator-v2-approval.json \
  --admitted-dir /private/pilot/admitted-001 \
  --exclusions /private/evaluator/withheld-exclusions.json \
  --output /private/pilot/audit-draft-001
```

The output must be a **new** directory. It is mode `0700`, with the proposed
`audit-manifest.json` mode `0600`, created through the pinned private-output
helper. Existing paths are never overwritten. The preparer first writes the
private **`audit-inspect-pending.json`** file, which is never sufficient for
approval or promotion. Only after inspection succeeds does it create
`audit-manifest.json` as an exclusive hard link through the pinned directory
descriptor; both names refer to the same private inode, without duplicate
content. The inspector report's manifest SHA-256 must match the exact staged
payload before any promotable name is created. The manifest includes the
original private passages and private absolute file paths: **never paste,
upload, or commit it**. The command prints only a text-free mechanical audit
summary after calling `training.corpus_admission inspect` on the written
pending file. On inspection failure the directory and pending file remain
private for diagnosis, but **no promotable `audit-manifest.json` has been
created**. There is no failure-path deletion, unlink, or rename: neither a
swapped parent directory nor a same-UID injected filename can cause the
helper to delete or overwrite another file. If post-inspection exclusive
linking fails, a non-promotable pending file remains and the helper refuses.
The same-UID hostile-process boundary itself is not established by this
tool; qualified operators must still protect local custody. Console errors
deliberately omit private filenames and passages.

The manifest's `provenance_reference` truthfully identifies the model-generated
source candidate and SHA. It never claims human authorship, independent
editorial endorsement, publication rights, or approval by a nonexistent
person. The exclusion file is never generated or modified by this helper.

## Still separate, still blocked

- A real operator must inspect the mechanical audit result and **separately**
  approve its exact corpus fingerprint under
  `aeonith.corpus_audit_synthetic_approval.v1`.
- A later `training.corpus_admission admit` must independently check that
  approval and create its own private receipt.
- Actual Trainer/PEFT output custody, a host-owned resource lease and a
  qualified model runtime are **not** established by these source operations.
- The candidate holdout is not a blind literary benchmark, and there are zero
  authorized optimizer steps solely from running this helper.

Like the existing candidate-admission tools, this helper does not make a
same-UID hostile-process boundary or authenticate the named human operator.
Windows private-output writes remain deliberately refused.
