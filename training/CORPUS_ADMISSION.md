# Supplemental private corpus audit

This optional, offline tool verifies source-level passage separation,
near-duplicate leakage and exact-hash human-attestation records for local
Aeonith training JSONL. It does **not** supersede the existing
training/corpus.py preflight or training/admit_candidates.py, does not
authenticate a rights holder, and does not grant GPU access or train a model.
Existing candidate drafts remain REVIEW PENDING until legitimately reviewed.

The tool provides three commands:

    python -m training.corpus_admission inspect --manifest /private/audit-manifest.json
    python -m training.corpus_admission admit --manifest /private/audit-manifest.json \
        --approval /private/approval.json --output /private/new-receipt-directory
    python -m training.corpus_admission verify --manifest /private/audit-manifest.json \
        --approval /private/approval.json --receipt /private/new-receipt-directory/admission_receipt.json

All three commands read strictly local private files. The first and third write
nothing; the second exclusively creates a new private directory containing one text-free
admission_receipt.json and refuses overwrite.
Do not place the manifest, private JSONL, approval, exclusion list, receipt or
manuscript excerpts in the Git checkout, an issue, a PR or a chat. On Windows,
private receipt *writes are currently disabled on ALL Python versions*:
the standalone tool cannot verify the destination parent's protected ACL and
handle-relative anti-reparse custody. Read-only inspection remains available.
Windows writes require a separately implemented and qualified host-owned
private-output broker, not a caller-provided bypass flag.

## Input contract

First prepare train.jsonl, validation.jsonl and holdout.jsonl in the already
defined Aeonith training/corpus.py record format. Each row must have a
unique ID, source ID, prompt/completion, recognized rights basis and explicit
JSON-boolean permissions. The original corpus validator still checks those
fields.

Create a private audit-manifest.json with:

    {
      "schema_version": "aeonith.corpus_audit_manifest.v1",
      "splits": {
        "train": {"path": "train.jsonl", "sha256": "<SHA-256>"},
        "validation": {"path": "validation.jsonl", "sha256": "<SHA-256>"},
        "holdout": {"path": "holdout.jsonl", "sha256": "<SHA-256>"}
      },
      "exclusions": {"path": "withheld-exclusions.json", "sha256": "<SHA-256>"},
      "sources": [
        {
          "source_id": "work-001",
          "source_text": "<the exact private original passage>",
          "rights_basis": "self_authored",
          "provenance_reference": "<operator-readable source provenance>",
          "rights_claimant": "<actual claimant identity>",
          "permission_to_train": true,
          "editorial_accepted": true
        }
      ]
    }

The displayed values are placeholders, NOT an approved corpus. Every source
ID in the JSONL must occur in the source list and vice versa. Licensed
sources additionally require a license_id; externally created materials need
a real, independently checked permission basis. The source_text field is
**private plaintext**: it is required so the validator can check that each
prompt actually contains its purported underlying passage. This prevents
changing a record's source ID or literary lens from hiding exact passage
reuse between TRAIN and holdout. Put the manifest on private storage and
never commit it. No source text or paths are included in the output receipt.

The withheld-exclusions.json file is deliberately separate from the corpus:

    {
      "schema_version": "aeonith.eval_exclusions.v1",
      "excluded_source_ids": ["sequestered-work-id"],
      "excluded_text_sha256": ["<SHA-256 of NFKC/casefold/whitespace-normalized text>"],
      "excluded_5gram_sha256": ["<SHA-256 of one five-token normalized window>"]
    }

At least one exclusion is required. A true evaluation steward should
generate source IDs and fingerprints outside training custody. The helper
function training.corpus_admission.fingerprints_for_text(text) returns a
normalized whole-text SHA-256 and all five-word shingle hashes without
returning the original text. Store only its hashes in exclusions.
The corpus audit refuses known excluded source IDs, normalized text matches
and forbidden five-word windows. It checks train, validation and holdout.

The tool also rejects:

- changed input file hashes, duplicate JSON keys and nonlocal/indirect paths;
- duplicate row IDs and source IDs crossing dataset splits (via the existing
  corpus validator);
- duplicate or near-duplicate source passages under different source IDs,
  including high-similarity short passages with a single changed word;
- duplicate prompt/completion text, including Unicode normalized duplicates;
- near-duplicate cross-split prompts/completions at eight or more overlapping
  five-word windows and a Jaccard score of at least 0.80;
- missing provenance, unknown rights, or missing explicit editorial approval.

This is a conservative, bounded audit of at most 500 rows, 16 MiB JSONL total,
8 MiB per metadata file,
and up to 804 Unicode word tokens per individual text field or source
passage. Oversized inputs are refused rather than silently skipping text.
Cross-language paraphrases, reworded passages, short overlaps and prior
unrecorded exposure can still evade mechanical checks. It is **not** proof
of evaluation independence or literary quality.

## Private approval is a second, human step

The inspect response contains corpus_fingerprint_sha256, which binds together
the exact audit manifest, the three JSONL file digests and the exclusion-file
digest. An operator can then make a separate private approval.json:

    {
      "schema_version": "aeonith.corpus_audit_approval.v1",
      "corpus_fingerprint_sha256": "<exact value returned by inspect>",
      "status": "APPROVED_PRIVATE_LOCAL_TRAINING",
      "permission_to_train": true,
      "rights_holder": {
        "identity": "<human rights holder or authorized rights officer>",
        "decision": "approve_rights",
        "attested_at_utc": "2026-11-02T18:00:00Z",
        "corpus_fingerprint_sha256": "<same exact value>"
      },
      "corpus_owner": {
        "identity": "<human corpus custodian>",
        "decision": "approve_corpus",
        "attested_at_utc": "2026-11-02T18:00:00Z",
        "corpus_fingerprint_sha256": "<same exact value>"
      },
      "data_steward": {
        "identity": "<independent steward>",
        "decision": "approve_data_use",
        "attested_at_utc": "2026-11-02T18:00:00Z",
        "corpus_fingerprint_sha256": "<same exact value>"
      },
      "editorial_reviewer": {
        "identity": "<independent editorial reviewer>",
        "decision": "approve_editorial_quality",
        "attested_at_utc": "2026-11-02T18:00:00Z",
        "corpus_fingerprint_sha256": "<same exact value>"
      }
    }

The rights-holder and corpus owner can be the same person, but the steward
and editor must be different from each other and from both. Every decision
must be bound to the same exact fingerprint. The CLI accepts only explicit
JSON boolean true, not placeholders, truthy strings or missing fields.

### Sole original owner option

If and only if **every** listed source is genuinely self-authored and wholly
owned by one individual, that owner may use the separate opt-in manifest below
instead of manufacturing independent reviewers or rights officers. The
`sources` entries must already declare `rights_basis: self_authored` and
`rights_claimant` exactly matching the real owner's identity (case-folded
comparison). The original corpus audit must still pass, including explicit
per-row editorial acceptance, no exclusions leaking across splits, and the
exact source and JSONL hashes.

```json
{
  "schema_version": "aeonith.corpus_audit_owner_approval.v1",
  "corpus_fingerprint_sha256": "<exact fingerprint from inspect>",
  "status": "APPROVED_SELF_AUTHORED_PRIVATE_TRAINING",
  "permission_to_train": true,
  "sole_owner_decision": {
    "identity": "<actual sole author/current owner matching every source>",
    "decision": "approve_sole_owner_original_private_training",
    "attested_at_utc": "2026-11-03T01:00:00Z",
    "corpus_fingerprint_sha256": "<same exact fingerprint>"
  }
}
```

This mode refuses licensed/public-domain/CC0/mixed-source declarations,
claimants other than the signing owner, and **any** declared adapter-publication
permission. Coauthored works, work-for-hire or subsequently assigned copyright
must not be relabeled as solely owned to pass. The receipt explicitly records
`approval_mode=sole_original_owner_self_authored`, no authenticated issuer,
no independent editorial reviewer, no adapter release permission, and no
trained model. All ownership and quality statements remain operator claims,
not legal findings. Previously saved receipts must be regenerated if this
newer source adds receipt fields, because `verify` compares the whole receipt.

**This manifest contains caller-provided names and decisions, not verifiable
signatures.** No code can establish that those people exist, made those
decisions, possess the claimed copyright, or performed a valid editorial
review. Those independent human and legal checks remain required for the
mixed-source path; sole original ownership uses an explicit self-attestation. A machine
receipt never automatically authorizes a model release; publishing adapter
weights requires a distinct decision.

If a filesystem write fails, the receipt may be incomplete; it must be
reviewed and never counted as successful admission. No overwrite is attempted.
On verified native Linux filesystems the destination directory and file are
opened relative to pinned directory descriptors, guarding against a symlink
swap of an ancestor after path validation. The writer rejects WSL DrvFS/9p,
NTFS and other unqualified mounts even when they emulate POSIX permission
bits; this does **not** isolate files against malicious processes already
running under the same operating-system identity. It does not establish
equivalent protection for *input* paths. Windows native receipt writes remain
disabled pending a qualified ACL/custody broker.

The admit command does not change or copy the input datasets, install weights,
create a training plan, run an optimizer or grant a host resource. After it
passes, `verify` rechecks the saved receipt against the current corpus and
approval bytes. `training.train_lora inspect-admission` additionally requires
the train/validation/holdout bytes in a separate Qwen3.5 training plan to
match this admitted corpus exactly. Both are read-only and return text-free
operator-attested receipts; neither authenticates human identities.

The operator must still establish the official checkpoint provenance and a
real host-owned resource grant. The CPU LoRA executor currently **refuses
optimizer launch** because its output directory and runtime/adapter writers
lack a qualified host-owned private-output custody broker. This guard remains
in place even with explicit `--execute` and a matching admission receipt;
the receipt does not authorize bypassing storage or host-resource safety.
The current QLoRA executor deliberately refuses CUDA until such a grant
mechanism exists and is qualified.
