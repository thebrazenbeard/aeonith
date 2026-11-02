# Private candidate admission (optional)

`python -m training.admit_candidates` converts a *reviewed and separately
approved* `aeonith.candidate_corpus.v1` proposal into private JSONL files for
the offline trainer. It **does not** approve the current 14 review-pending
Aeonith drafts, install weights, start training, validate copyright, or authorize
publication. Only the user's real rights-holder and an independent human data
steward and editorial reviewer can make those decisions.

The candidate proposal remains immutable. Make a **separate private** JSON
approval manifest after those human reviews. It has this structure (the
illustrative `null`/`false` fields intentionally **fail** admission):

```json
{
  "schema_version": "aeonith.candidate_admission.v1",
  "candidate_sha256": "<exact lowercase SHA-256 of the private candidates.json>",
  "approval_status": "REVIEW_PENDING_NOT_TRAINABLE",
  "permission_to_train": false,
  "rights_holder_decision": null,
  "independent_data_steward_decision": null,
  "editorial_decision": null,
  "records": []
}
```

For a real private-local approval, the manifest must explicitly set
`approval_status` to `APPROVED_FOR_PRIVATE_LOCAL_TRAINING`, and
`permission_to_train` to the JSON boolean `true`. The three decision objects
must have **different, genuinely independent identities** and these exact
fields:

- `identity`: the actual human or responsible organization;
- `decision`: `approve_local_training` for rights-holder and steward,
  `approve_editorial_targets` for the editorial reviewer;
- `attested_at_utc`: an actual UTC timestamp, e.g. `2026-11-02T17:00:00Z`;
- `candidate_sha256`: the *same exact hash* of the approved candidate file.

`records` must contain exactly one decision per candidate `id`, with matching
`source_id`, verified `rights_basis` (`self_authored`, `public_domain`, `cc0`,
or `licensed`), `permission_to_train: true`, and `editorial_accepted: true`.
For licensed sources an actual `license_id` is required. The optional
`permission_to_publish_adapter` defaults to `false`; setting it to `true`
only records a per-item claim, **not a release authorization**. There is no
automatic transfer of approval from a global status to individual works.

Identity strings and timestamps are **self-reported**, not cryptographic
signatures or external independent attestation. The tool cannot detect forged
names, false ownership claims, superficial editor review, or semantic dataset
leakage. It reports
`operator_attested_not_cryptographically_verified` explicitly.

Run only when the proposal, approval manifest and new output directory are
all on private local storage *outside the Git checkout*:

```bash
python -m training.admit_candidates \
  --candidates /private/reviewed/candidates.json \
  --approval /private/reviewed/approval.json \
  --output /private/reviewed/approved-jsonl
```

This never calls a model or network service. It runs exact SHA-256, strict
schema/boolean, distinct-identity, per-work train/editorial permission,
literal-quote/lens, source-split overlap and non-overwrite checks *before*
writing. It then exclusively creates `train.jsonl`, `validation.jsonl`,
`holdout.jsonl` and a **text-free** `admission_receipt.json` that reports
which critique lenses occur in each split and which of the 14 canonical lenses
are missing from training. The tool reports coverage; it does not require all
14 lenses for a tiny optimizer smoke test or claim broad literary competence.
On a filesystem
error after the directory is created, an incomplete directory may remain;
manually review it and do not treat it as an approved result without the
receipt. The output's OS permissions and backups remain operator concerns.

The converter does not create a training plan. After separate model/base
checkpoint authorization, the local operator must explicitly build the plan
described in [README.md](README.md) and run its offline preflight. Keep the
holdout from the current visible proposal out of any claim of blinded
generalization, even if its records are technically admitted. Compare a
sequestered evaluation set with a frozen base before calling Aeonith useful.
