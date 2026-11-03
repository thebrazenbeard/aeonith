# Model-generated synthetic literary pilot: private-only admission

This is a third, narrowly scoped admission mode, **not** the human-authored
sole-owner mode or the independent multi-party mode. It exists so a small
model-generated pilot does not masquerade as material personally authored by
the operator. It grants no permission to copy a third-party manuscript,
publish an adapter, or claim independent human editorial quality.

1. Generate a new candidate proposal using original synthetic passages and
   critique targets, all on private local storage outside Git. Its root is
   `aeonith.candidate_corpus.v1`, status `REVIEW_PENDING_NOT_TRAINABLE`,
   with the ordinary `examples` structure. In addition it must include:

   ```json
   "generator_provenance": {
     "origin": "model_generated_synthetic",
     "generator": "ChatGPT",
     "third_party_text_used": false,
     "human_authorship_claimed": false,
     "publication_authorized": false
   }
   ```

2. **Only after generation and inspection**, the real operator may write a
   separate private approval of the *exact* SHA-256 of `candidates.json`.
   Do not infer this from a prior go-ahead to generate data. The tool does not
   create or prefill approvals:

   ```json
   {
     "schema_version": "aeonith.candidate_synthetic_admission.v1",
     "candidate_sha256": "<exact SHA-256 of candidates.json>",
     "approval_status": "APPROVED_MODEL_GENERATED_PRIVATE_LOCAL_TRAINING",
     "permission_to_train": true,
     "operator_decision": {
       "identity": "<actual operator approving these exact bytes>",
       "decision": "approve_exact_model_generated_private_training",
       "attested_at_utc": "<actual UTC timestamp ending in Z>",
       "candidate_sha256": "<same exact SHA-256>"
     },
     "records": [
       {"id": "<candidate ID>", "source_id": "<candidate source ID>",
        "rights_basis": "synthetic_generated", "permission_to_train": true,
        "editorial_accepted": false, "permission_to_publish_adapter": false}
     ]
   }
   ```

   Repeat the record decision for **each** candidate; a placeholder is not
   admission. Identity strings are operator assertions, not signatures.

   If a record does not meet the operator's standards, use
   `aeonith.candidate_synthetic_admission.v2` with the same top-level fields,
   but require an explicit `disposition` on **every** record:

   ```json
   "records": [
     {"id": "<candidate ID retained>", "source_id": "<source ID>",
      "rights_basis": "synthetic_generated", "disposition": "admit",
      "permission_to_train": true, "editorial_accepted": false,
      "permission_to_publish_adapter": false},
     {"id": "<candidate ID rejected>", "source_id": "<source ID>",
      "rights_basis": "synthetic_generated", "disposition": "reject",
      "reason_code": "quality", "permission_to_train": false,
      "editorial_accepted": false, "permission_to_publish_adapter": false},
     {"id": "<candidate ID excluded>", "source_id": "<source ID>",
      "rights_basis": "synthetic_generated", "disposition": "exclude",
      "reason_code": "rights_unclear", "permission_to_train": false,
      "editorial_accepted": false, "permission_to_publish_adapter": false}
   ]
   ```

   Valid exclusion reasons: `rights_unclear`, `quality`, `duplicate`,
   `out_of_scope`, `other`. This is only a *shape example*: the actual manifest
   must enumerate each of the candidate IDs once and bind the candidate's
   exact SHA-256. Rejected/excluded rows are omitted from the emitted JSONL;
   all train/validation/holdout splits must still retain at least one admitted
   record. The text-free receipt reports aggregate disposition counts.
   Revision to any decision requires a new approval-manifest digest and later
   a new, separate corpus-audit approval. No program may preapprove for the
   operator or reinterpret `exclude` as consent.

3. `python -m training.admit_candidates --candidates PRIVATE/candidates.json`
   `--approval PRIVATE/approval.json --output PRIVATE/new-admitted-directory`
   mechanically checks exact candidate hashes, record-level decisions, quote
   structure, and split separation. On qualified native Linux it creates
   private `train.jsonl`, `validation.jsonl`, `holdout.jsonl` and a text-free
   receipt. It refuses Windows writes until private-output ACL/handle custody
   is qualified. Every output row includes `rights_basis: synthetic_generated`,
   `source_origin: model_generated_synthetic`, and `permission_to_publish_adapter: false`.

4. Build a separate private `aeonith.corpus_audit_manifest.v1` with the three
   exact split paths/hashes and a withheld-exclusions file as described in
   `CORPUS_ADMISSION.md`. Add root `candidate_sha256` and, for every source:
   `source_origin: model_generated_synthetic`, `source_generator: ChatGPT`,
   `source_candidate_sha256: <same exact candidate SHA-256>`,
   `rights_basis: synthetic_generated`, `permission_to_train: true`,
   `editorial_accepted: false`, plus source ID/text and a factual
   `provenance_reference`. Do **not** set `rights_claimant` to a fabricated human.
   The audit rejects mixed synthetic/human-source manifests and checks
   duplicate, near-duplicate and excluded-text overlap mechanically.

5. Only after the `corpus_admission inspect` output is frozen, a separate
   operator acknowledgment may be provided for its exact fingerprint:

   ```json
   {
     "schema_version": "aeonith.corpus_audit_synthetic_approval.v1",
     "candidate_sha256": "<same exact candidate SHA-256>",
     "corpus_fingerprint_sha256": "<exact inspect value>",
     "status": "APPROVED_MODEL_GENERATED_PRIVATE_TRAINING",
     "permission_to_train": true,
     "operator_decision": {
       "identity": "<actual operator>",
       "decision": "approve_exact_model_generated_private_training",
       "attested_at_utc": "<actual UTC timestamp ending in Z>",
       "corpus_fingerprint_sha256": "<same exact inspect value>"
     }
   }
   ```

   `training.corpus_admission admit` can then save a private receipt on a
   qualified native Linux filesystem; `verify` checks it against current
   exact corpus/approval bytes before later use by `train_lora inspect-admission`.

**Limits:** Neither tool proves that the generator did not reproduce a
third-party work, that a user truly signed the JSON, or that semantic leakage
is absent. Human review is not claimed. Visible candidate holdout is not a
blind external evaluation. Source approval is **not** a qualified model load,
host lease, protected optimizer I/O, neural weight update, or deployment.
Existing CPU/GPU training gates remain closed until separately qualified.
