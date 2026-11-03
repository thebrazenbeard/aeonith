"""Supplemental offline audit of already-structured Aeonith JSONL corpora.

This is NOT a trusted rights authority. Existing training.corpus.inspect_plan
remains the training preflight; this adds mechanical provenance and leakage
checks and records human claims bound to exact private file hashes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
from typing import Any

from .corpus import CorpusError, RIGHTS_BASIS, SPLITS, _check_isolation, _read_split_bound


class AdmissionError(ValueError):
    """Corpus cannot be mechanically admitted under the supplied claims."""


REPO_ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[a-f0-9]{64}$")
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_TOTAL_ROWS = 500
MAX_TOTAL_TEXT_BYTES = 16 * 1024 * 1024
MAX_SHINGLES = 800
BAD_IDENTITIES = {"", "unknown", "pending", "todo", "tbd", "none"}
ROLES = {
    "rights_holder": "approve_rights",
    "corpus_owner": "approve_corpus",
    "data_steward": "approve_data_use",
    "editorial_reviewer": "approve_editorial_quality",
}


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionError("duplicate metadata JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise AdmissionError("non-finite JSON constant")


def _read_metadata(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_METADATA_BYTES:
        raise AdmissionError("missing or oversized metadata file")
    raw = path.read_bytes()
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                         parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("invalid metadata JSON") from exc
    if not isinstance(obj, dict):
        raise AdmissionError("metadata must be a JSON object")
    return obj, hashlib.sha256(raw).hexdigest()


def _exact(obj: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(obj, dict) or set(obj) - required - optional or required - set(obj):
        raise AdmissionError("invalid metadata fields")
    return obj


def _indirect_path(path: Path) -> bool:
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            return True
        if os.name == "nt":
            try:
                attrs = component.lstat().st_file_attributes
            except FileNotFoundError:
                continue
            if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return True
    return False


def _git_checkout_ancestor(path: Path) -> bool:
    # Check *every* surrounding worktree/repository marker, not just the
    # checkout containing this code. Git worktrees use a .git FILE; ordinary
    # clones use a .git DIRECTORY.
    for ancestor in (path, *path.parents):
        marker = ancestor / ".git"
        if marker.is_dir() and (marker / "HEAD").is_file():
            return True
        if marker.is_file():
            try:
                if marker.read_text(encoding="utf-8", errors="ignore").startswith("gitdir:"):
                    return True
            except OSError:
                raise AdmissionError("cannot verify private path Git marker")
    return False


def _private_file(raw_value: Any, parent: Path) -> Path:
    if not isinstance(raw_value, str) or not raw_value.strip() or "://" in raw_value or raw_value.startswith("\\\\"):
        raise AdmissionError("private local file path required")
    raw = Path(raw_value).expanduser()
    candidate = raw if raw.is_absolute() else parent / raw
    if _indirect_path(candidate):
        raise AdmissionError("private paths cannot traverse symlinks or junctions")
    path = candidate.resolve()
    if str(path).startswith("\\\\"):
        raise AdmissionError("network paths are not permitted")
    if path == REPO_ROOT or REPO_ROOT in path.parents or _git_checkout_ancestor(path):
        raise AdmissionError("private corpus must remain outside all git checkouts")
    if not path.is_file():
        raise AdmissionError("private corpus file missing")
    return path


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _digest_text(value: str) -> str:
    return hashlib.sha256(_normalized(value).encode("utf-8")).hexdigest()


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", _normalized(value), flags=re.UNICODE)


def _shingles(value: str) -> set[str]:
    words = _words(value)
    if len(words) < 5:
        return set()
    # Fail closed instead of silently dropping trailing text from the audit.
    if len(words) > MAX_SHINGLES + 4:
        raise AdmissionError("text exceeds bounded shingle audit capacity")
    return {hashlib.sha256(" ".join(words[i:i + 5]).encode("utf-8")).hexdigest()
            for i in range(len(words) - 4)}


def fingerprints_for_text(value: str) -> dict[str, Any]:
    """Generate text-free hashes for an independently withheld exclusion set."""
    if not isinstance(value, str) or not value.strip() or len(value) > 12000:
        raise AdmissionError("invalid withheld text")
    return {"text_sha256": _digest_text(value),
            "five_word_shingle_sha256": sorted(_shingles(value))}


def _excluded(obj: dict) -> tuple[set[str], set[str], set[str]]:
    _exact(obj, {"schema_version", "excluded_source_ids", "excluded_text_sha256",
                 "excluded_5gram_sha256"})
    if obj["schema_version"] != "aeonith.eval_exclusions.v1":
        raise AdmissionError("unsupported exclusion schema")
    result: list[set[str]] = []
    for key in ("excluded_source_ids", "excluded_text_sha256", "excluded_5gram_sha256"):
        values = obj[key]
        if not isinstance(values, list) or len(values) > 100000:
            raise AdmissionError("invalid exclusion list")
        if any(not isinstance(v, str) or not v for v in values) or len(set(values)) != len(values):
            raise AdmissionError("invalid or duplicate exclusion value")
        if key != "excluded_source_ids" and any(not HEX64.fullmatch(v) for v in values):
            raise AdmissionError("invalid exclusion digest")
        result.append(set(values))
    if not any(result):
        raise AdmissionError("withheld evaluation exclusions cannot be empty")
    return result[0], result[1], result[2]


def _source_metadata(sources: Any, observed: dict[str, list[dict]]) -> dict[str, str]:
    if not isinstance(sources, list) or len(sources) > MAX_TOTAL_ROWS:
        raise AdmissionError("invalid source provenance list")
    mapping: dict[str, dict] = {}
    source_text: dict[str, str] = {}
    for source in sources:
        item = _exact(source, {"source_id", "source_text", "rights_basis", "provenance_reference",
                               "rights_claimant", "permission_to_train",
                               "editorial_accepted"}, {"license_id"})
        sid = item["source_id"]
        if not isinstance(sid, str) or sid in mapping or sid not in observed:
            raise AdmissionError("unknown or duplicate source provenance")
        for key in ("provenance_reference", "rights_claimant"):
            value = item[key]
            if not isinstance(value, str) or not 2 <= len(value.strip()) <= 512 or value.strip().casefold() in BAD_IDENTITIES:
                raise AdmissionError("unknown source provenance or claimant")
        if (not isinstance(item["rights_basis"], str) or
                item["rights_basis"] not in RIGHTS_BASIS or
                item["rights_basis"] != observed[sid][0]["rights_basis"] or
                item["permission_to_train"] is not True or
                item["editorial_accepted"] is not True):
            raise AdmissionError("source has unresolved rights or editorial consent")
        if item["rights_basis"] == "licensed":
            if not isinstance(item.get("license_id"), str) or not item["license_id"].strip():
                raise AdmissionError("licensed source requires license reference")
        passage = item["source_text"]
        if not isinstance(passage, str) or not passage.strip() or len(passage) > 12000:
            raise AdmissionError("source text missing or oversized")
        # Prove that each row carries the declared source passage: a claimed
        # hash alone is forgeable and cannot detect passage reuse under new IDs.
        if any(_normalized(passage) not in _normalized(row["prompt"])
               for row in observed[sid]):
            raise AdmissionError("source passage is not contained in its training prompt")
        source_text[sid] = passage
        mapping[sid] = item
    if set(mapping) != set(observed):
        raise AdmissionError("provenance missing for one or more sources")
    return source_text


def inspect(manifest_path: str | Path) -> dict[str, Any]:
    """Check private bytes, row contracts, duplicates and excluded fingerprints."""
    manifest_file = _private_file(str(manifest_path), Path.cwd())
    manifest, manifest_sha = _read_metadata(manifest_file)
    _exact(manifest, {"schema_version", "splits", "exclusions", "sources"})
    if manifest["schema_version"] != "aeonith.corpus_audit_manifest.v1":
        raise AdmissionError("unsupported corpus audit manifest")
    split_desc = _exact(manifest["splits"], set(SPLITS))
    excluded_desc = _exact(manifest["exclusions"], {"path", "sha256"})
    digests: dict[str, str] = {}
    dataset: dict[str, list[dict]] = {}
    paths: set[Path] = set()
    total_bytes = 0
    for split in SPLITS:
        info = _exact(split_desc[split], {"path", "sha256"})
        path = _private_file(info["path"], manifest_file.parent)
        if path in paths or not isinstance(info["sha256"], str) or not HEX64.fullmatch(info["sha256"]):
            raise AdmissionError("invalid or overlapping split")
        paths.add(path)
        rows, actual, byte_count = _read_split_bound(path, split)
        if actual != info["sha256"]:
            raise AdmissionError("split file fingerprint mismatch")
        digests[split] = actual
        dataset[split] = rows
        total_bytes += byte_count
    if sum(map(len, dataset.values())) > MAX_TOTAL_ROWS or total_bytes > MAX_TOTAL_TEXT_BYTES:
        raise AdmissionError("corpus exceeds bounded offline audit capacity")
    _check_isolation(dataset)
    eval_path = _private_file(excluded_desc["path"], manifest_file.parent)
    if eval_path in paths or not isinstance(excluded_desc["sha256"], str) or not HEX64.fullmatch(excluded_desc["sha256"]):
        raise AdmissionError("invalid exclusion manifest")
    exclusions, exclusions_sha = _read_metadata(eval_path)
    if exclusions_sha != excluded_desc["sha256"]:
        raise AdmissionError("evaluation exclusion fingerprint mismatch")
    forbidden_source, forbidden_text, forbidden_shingles = _excluded(exclusions)
    observed: dict[str, list[dict]] = {}
    source_split: dict[str, str] = {}
    exact_text: set[str] = set()
    signatures: list[tuple[str, set[str]]] = []
    shingle_index: dict[str, list[int]] = {}
    for split in SPLITS:
        for row in dataset[split]:
            sid = row["source_id"]
            previous = observed.get(sid)
            if previous and (previous[0]["rights_basis"] != row["rights_basis"]):
                raise AdmissionError("conflicting rights declarations for one source")
            observed.setdefault(sid, []).append(row)
            source_split[sid] = split
            if sid in forbidden_source:
                raise AdmissionError("training source intersects withheld evaluation source")
            for field in ("prompt", "completion"):
                value = row[field]
                digest = _digest_text(value)
                if digest in exact_text or digest in forbidden_text:
                    raise AdmissionError("duplicated or withheld training text")
                exact_text.add(digest)
                grams = _shingles(value)
                if forbidden_shingles.intersection(grams):
                    raise AdmissionError("training text overlaps withheld evaluation shingles")
                # A conservative near-duplicate screen; short non-overlapping
                # texts and semantic paraphrases still require human review.
                if len(grams) >= 8:
                    candidate_counts: Counter[int] = Counter(
                        index for gram in grams for index in shingle_index.get(gram, ())
                        if signatures[index][0] != split
                    )
                    for index, shared in candidate_counts.items():
                        prev = signatures[index][1]
                        if shared >= 8 and shared / len(prev | grams) >= 0.80:
                            raise AdmissionError("near-duplicate text crosses dataset splits")
                index = len(signatures)
                signatures.append((split, grams))
                for gram in grams:
                    shingle_index.setdefault(gram, []).append(index)
    source_text = _source_metadata(manifest["sources"], observed)
    prior_sources: list[tuple[str, str, set[str], list[str]]] = []
    for source_id, passage in sorted(source_text.items()):
        split = source_split[source_id]
        text_hash = _digest_text(passage)
        grams = _shingles(passage)
        words = _words(passage)
        if text_hash in forbidden_text or forbidden_shingles.intersection(grams):
            raise AdmissionError("source passage overlaps withheld evaluation text")
        for earlier_split, earlier_hash, earlier_grams, earlier_words in prior_sources:
            if text_hash == earlier_hash:
                raise AdmissionError("identical source passage reused under another ID")
            if (earlier_split != split and len(grams) >= 4 and len(earlier_grams) >= 4
                    and len(grams & earlier_grams) >= 3
                    and len(grams & earlier_grams) / len(grams | earlier_grams) >= 0.65):
                raise AdmissionError("near-duplicate source passages cross dataset splits")
            # Five-word shingles can miss an otherwise almost identical
            # 10-word passage when just its central token changes.
            if (earlier_split != split and 6 <= len(words) <= 64
                    and 6 <= len(earlier_words) <= 64
                    and abs(len(words) - len(earlier_words)) <= max(len(words), len(earlier_words)) * 0.20
                    and len(set(words) & set(earlier_words))
                    >= 0.75 * min(len(set(words)), len(set(earlier_words)))
                    and SequenceMatcher(None, words, earlier_words, autojunk=False).ratio() >= 0.90):
                raise AdmissionError("near-duplicate source passages cross dataset splits")
        prior_sources.append((split, text_hash, grams, words))
    fingerprint = hashlib.sha256(json.dumps({
        "manifest_sha256": manifest_sha, "split_sha256": digests,
        "exclusions_sha256": exclusions_sha,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema_version": "aeonith.corpus_audit_receipt.v1",
        "status": "mechanically_checked_not_approved_or_trained",
        "manifest_sha256": manifest_sha,
        "corpus_fingerprint_sha256": fingerprint,
        "exclusions_sha256": exclusions_sha,
        "split_sha256": digests,
        "split_counts": {split: len(dataset[split]) for split in SPLITS},
        "source_count": len(observed),
        "independent_rights_authentication": False,
        "blind_holdout_qualified": False,
        "semantic_leakage_absent_proven": False,
        "model_trained": False,
    }


def _attestation(obj: Any, role: str, fingerprint: str) -> str:
    data = _exact(obj, {"identity", "decision", "attested_at_utc", "corpus_fingerprint_sha256"})
    identity = data["identity"]
    if not isinstance(identity, str) or not 2 <= len(identity.strip()) <= 160 or identity.strip().casefold() in BAD_IDENTITIES:
        raise AdmissionError("missing attestor identity")
    if data["decision"] != ROLES[role] or data["corpus_fingerprint_sha256"] != fingerprint:
        raise AdmissionError("attestation does not cover exact corpus fingerprint")
    when = data["attested_at_utc"]
    if not isinstance(when, str) or not when.endswith("Z"):
        raise AdmissionError("invalid attestation timestamp")
    try:
        parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionError("invalid attestation timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise AdmissionError("invalid attestation timezone")
    return identity.strip().casefold()


def check_approvals(manifest_path: str | Path, approval_path: str | Path) -> dict[str, Any]:
    """Read-only verification of exact corpus hashes and operator attestations.

    Identity strings are not cryptographic signatures; this never proves that
    the named people made the statements or that copyright is resolved.
    """
    receipt = inspect(manifest_path)
    approvals, approval_sha = _read_metadata(_private_file(str(approval_path), Path.cwd()))
    _exact(approvals, {"schema_version", "corpus_fingerprint_sha256", "status",
                       "permission_to_train", *ROLES})
    if (approvals["schema_version"] != "aeonith.corpus_audit_approval.v1"
            or approvals["corpus_fingerprint_sha256"] != receipt["corpus_fingerprint_sha256"]
            or approvals["status"] != "APPROVED_PRIVATE_LOCAL_TRAINING"
            or approvals["permission_to_train"] is not True):
        raise AdmissionError("corpus not approved for private local training")
    identities = {role: _attestation(approvals[role], role, receipt["corpus_fingerprint_sha256"])
                  for role in ROLES}
    if len({identities["rights_holder"], identities["data_steward"],
            identities["editorial_reviewer"]}) != 3:
        raise AdmissionError("rights, steward and editorial attestors must be distinct")
    if identities["corpus_owner"] in {identities["data_steward"], identities["editorial_reviewer"]}:
        raise AdmissionError("data steward/editor must be distinct from corpus owner")
    result = {
        **receipt,
        "status": "operator_attested_private_training_only_not_trained",
        "approval_sha256": approval_sha,
        "attestation_identities_independently_authenticated": False,
        "rights_and_editorial_claims_operator_attested_only": True,
        "adapter_publication_authorized": False,
    }
    return result


def verify_admission(manifest_path: str | Path, approval_path: str | Path,
                     receipt_path: str | Path) -> dict[str, Any]:
    """Recheck a saved receipt against *current* private source/approval bytes.

    The receipt is an operator statement, not a trusted rights signature. This
    prevents accidental corpus substitution and stale/fabricated standalone
    receipt contents from silently authorizing an optimizer run.
    """
    expected = check_approvals(manifest_path, approval_path)
    saved, _ = _read_metadata(_private_file(str(receipt_path), Path.cwd()))
    if saved != expected:
        raise AdmissionError("admission receipt mismatches current corpus or approvals")
    return expected


def admit(manifest_path: str | Path, approval_path: str | Path,
          output_path: str | Path) -> dict[str, Any]:
    """Record caller-attested decisions in a NEW private receipt directory."""
    result = check_approvals(manifest_path, approval_path)
    raw = Path(output_path).expanduser()
    candidate = raw if raw.is_absolute() else Path.cwd() / raw
    if _indirect_path(candidate):
        raise AdmissionError("receipt path must not traverse symlinks or junctions")
    if raw.exists() or raw.is_symlink():
        raise AdmissionError("receipt destination already exists")
    path = candidate.resolve()
    if str(path).startswith("\\\\"):
        raise AdmissionError("network paths are not permitted")
    if path == REPO_ROOT or REPO_ROOT in path.parents or _git_checkout_ancestor(path) or not path.parent.is_dir():
        raise AdmissionError("receipt must remain outside git checkouts")
    # No verified Windows private-parent ACL or handle-relative anti-reparse
    # custody exists for this standalone tool. A Python version check alone
    # cannot establish those properties: leave inspection usable, deny writes.
    if os.name == "nt":
        raise AdmissionError("private receipt writes on Windows require a qualified ACL/custody broker")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise AdmissionError("receipt destination already exists") from exc
    fd = os.open(path / "admission_receipt.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except BaseException:
        # Leave an incomplete receipt for explicit operator review.
        raise
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline supplemental Aeonith corpus audit; no training or publication")
    parser.add_argument("action", choices=("inspect", "admit", "verify"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect":
            if args.approval or args.output or args.receipt:
                raise AdmissionError("inspect does not accept approval, output or receipt")
            result = inspect(args.manifest)
        elif args.action == "admit":
            if not args.approval or not args.output or args.receipt:
                raise AdmissionError("admit requires approval and output")
            result = admit(args.manifest, args.approval, args.output)
        else:
            if not args.approval or not args.receipt or args.output:
                raise AdmissionError("verify requires approval and receipt, without output")
            result = verify_admission(args.manifest, args.approval, args.receipt)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AdmissionError, CorpusError, OSError, ValueError) as exc:
        print(f"Corpus audit refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
