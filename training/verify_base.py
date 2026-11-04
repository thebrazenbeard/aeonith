"""Offline byte-level check of a local Qwen3.5 checkpoint against supplied digests.

This verifies agreement between two local artifacts. It does NOT authenticate
the manifest's issuer or the declared Hugging Face Git revision. Only a human
operator can establish the manifest's independent trusted provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from .corpus import ALLOWED_MODELS


class BaseVerificationError(ValueError):
    """Local files do not satisfy the supplied checkpoint provenance claim."""


_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_INDEX_BYTES = 2 * 1024 * 1024
_MAX_FILES = 256
_RUNTIME_SUFFIXES = (".json", ".safetensors", ".jinja", ".model", ".txt")
_TOKENIZER_NAMES = {"tokenizer.json", "tokenizer.model", "vocab.json"}


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BaseVerificationError("duplicate JSON fields")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise BaseVerificationError("non-finite JSON value")


def _read_json(path: Path, limit: int) -> dict[str, Any]:
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise BaseVerificationError("missing or oversized local JSON")
    try:
        value = json.loads(path.read_text(encoding="utf-8"),
                           object_pairs_hook=_no_duplicate_keys,
                           parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, BaseVerificationError):
            raise
        raise BaseVerificationError("invalid local JSON") from exc
    if not isinstance(value, dict):
        raise BaseVerificationError("expected JSON object")
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _no_symlink_ancestors(path: Path) -> None:
    # Check lexical ancestors before .resolve(), otherwise their symlink
    # identities would be lost. This is an offline snapshot check, not a
    # defense against concurrent host-level filesystem mutation (TOCTOU).
    for item in (path, *path.parents):
        if _linked(item):
            raise BaseVerificationError("symlink in checkpoint/manifest path")


def _linked(path: Path) -> bool:
    # Windows junctions can redirect directories without being reported by
    # is_symlink(). Python 3.12+ exposes is_junction() for this case.
    checker = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(checker and checker())


def _name(value: Any) -> str:
    if (not isinstance(value, str) or not _FILENAME.fullmatch(value)
            or value in {".", ".."} or "/" in value or "\\" in value or ":" in value):
        raise BaseVerificationError("invalid fingerprint filename")
    return value


def _expected_files(manifest: dict) -> tuple[str, str, dict[str, dict]]:
    if set(manifest) != {"schema_version", "upstream_model_id", "upstream_revision", "files"}:
        raise BaseVerificationError("invalid expected-file manifest fields")
    if manifest["schema_version"] != "aeonith.expected_base_files.v1":
        raise BaseVerificationError("unsupported expected-file manifest schema")
    model = manifest["upstream_model_id"]
    revision = manifest["upstream_revision"]
    if not isinstance(model, str) or model not in ALLOWED_MODELS:
        raise BaseVerificationError("unsupported upstream model")
    if not isinstance(revision, str) or not _HEX40.fullmatch(revision):
        raise BaseVerificationError("invalid upstream revision")
    entries = manifest["files"]
    if not isinstance(entries, list) or not 3 <= len(entries) <= _MAX_FILES:
        raise BaseVerificationError("invalid expected-file count")
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "bytes", "sha256"}:
            raise BaseVerificationError("invalid fingerprint entry")
        name = _name(entry["name"])
        size, digest = entry["bytes"], entry["sha256"]
        if name in expected:
            raise BaseVerificationError("duplicate fingerprint filename")
        if (type(size) is not int or not 0 < size <= 2**44 or not isinstance(digest, str)
                or not _HEX64.fullmatch(digest)):
            raise BaseVerificationError("invalid file fingerprint")
        expected[name] = {"bytes": size, "sha256": digest}
    return model, revision, expected


def _shards(base: Path, observed: set[str]) -> int:
    weights = {name for name in observed if name.endswith(".safetensors")}
    if not weights:
        raise BaseVerificationError("checkpoint has no safetensors weights")
    index = base / "model.safetensors.index.json"
    if not index.is_file():
        if weights != {"model.safetensors"}:
            raise BaseVerificationError("checkpoint shard filenames require an index")
        return 1
    payload = _read_json(index, _MAX_INDEX_BYTES)
    mapping = payload.get("weight_map")
    if not isinstance(mapping, dict) or not mapping:
        raise BaseVerificationError("invalid checkpoint shard index")
    named = set()
    for tensor, filename in mapping.items():
        if not isinstance(tensor, str) or not tensor or len(tensor) > 1024:
            raise BaseVerificationError("invalid tensor name in shard index")
        filename = _name(filename)
        if not filename.endswith(".safetensors"):
            raise BaseVerificationError("invalid checkpoint shard reference")
        named.add(filename)
    if named != weights:
        raise BaseVerificationError("checkpoint shard index does not cover exact weight files")
    return len(weights)


def verify_checkpoint(base_dir: str | Path, manifest_path: str | Path, *,
                      expected_model: str | None = None,
                      expected_revision: str | None = None) -> dict[str, Any]:
    """Verify local bytes against an independently supplied *untrusted* manifest.

    `expected_model` and `expected_revision` may bind a separately authorized
    training plan; they are not remote authority or a download instruction.
    """
    base_raw, manifest_raw = Path(base_dir).expanduser().absolute(), Path(manifest_path).expanduser().absolute()
    if os.name == "nt" and (str(base_raw).startswith("\\\\") or str(manifest_raw).startswith("\\\\")):
        raise BaseVerificationError("UNC paths are not local checkpoint evidence")
    _no_symlink_ancestors(base_raw)
    _no_symlink_ancestors(manifest_raw)
    base, manifest_file = base_raw.resolve(), manifest_raw.resolve()
    if not base.is_dir() or not manifest_file.is_file() or base == manifest_file.parent or base in manifest_file.parents:
        raise BaseVerificationError("checkpoint directory and separate manifest file required")
    manifest = _read_json(manifest_file, _MAX_MANIFEST_BYTES)
    model, revision, expected = _expected_files(manifest)
    if expected_model is not None and expected_model != model:
        raise BaseVerificationError("expected model does not match supplied manifest")
    if expected_revision is not None and expected_revision != revision:
        raise BaseVerificationError("expected revision does not match supplied manifest")

    # Reject symlinks even if an entry is not listed. Unknown non-runtime docs
    # (e.g. README) are not part of the model-loading claim.
    files = list(base.iterdir())
    if len(files) > _MAX_FILES + 16:
        raise BaseVerificationError("too many local checkpoint files")
    if any(_linked(item) for item in files):
        raise BaseVerificationError("symlink in local checkpoint directory")
    if any(not item.is_file() for item in files):
        raise BaseVerificationError("unexpected subdirectory or special checkpoint entry")
    observed = {item.name for item in files if item.name.endswith(_RUNTIME_SUFFIXES)}
    if observed != set(expected):
        raise BaseVerificationError("expected-file manifest does not cover exact runtime assets")
    if "config.json" not in observed or not observed.intersection(_TOKENIZER_NAMES):
        raise BaseVerificationError("checkpoint configuration or tokenizer missing")
    config = _read_json(base / "config.json", _MAX_MANIFEST_BYTES)
    if config.get("model_type") not in {"qwen3_5", "qwen3_5_text"}:
        raise BaseVerificationError("local configuration is not Qwen3.5")
    shard_count = _shards(base, observed)
    for filename, fingerprint in expected.items():
        path = base / filename
        if not path.is_file() or path.stat().st_size != fingerprint["bytes"] or _sha256(path) != fingerprint["sha256"]:
            raise BaseVerificationError("local checkpoint fingerprint mismatch")
    return {
        "schema_version": "aeonith.base_file_verification.v1",
        "status": "local_bytes_match_supplied_manifest_not_origin_authenticated",
        "upstream_model_id": model,
        "upstream_revision_declared_not_live_verified": revision,
        "expected_manifest_sha256": _sha256(manifest_file),
        "files_verified": len(expected),
        "weight_shards_verified": shard_count,
        "upstream_origin_authenticated": False,
        "host_training_qualified": False,
        "limitations": [
            "manifest was operator supplied; identity and publisher origin have not been authenticated",
            "file bytes and index match an expectation, not a proven functional model or training result",
            "file substitution during hashing is outside this snapshot check's threat model",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Qwen3.5 checkpoint fingerprint comparison; never downloads")
    parser.add_argument("--base", required=True, type=Path, help="local materialized Transformers safetensors directory")
    parser.add_argument("--manifest", required=True, type=Path, help="separately obtained trusted expected-file hashes")
    parser.add_argument("--expected-model", required=True, choices=sorted(ALLOWED_MODELS))
    parser.add_argument("--expected-revision", required=True, help="40-character intended upstream commit")
    args = parser.parse_args(argv)
    try:
        receipt = verify_checkpoint(args.base, args.manifest,
                                    expected_model=args.expected_model,
                                    expected_revision=args.expected_revision)
    except (BaseVerificationError, OSError) as exc:
        # Never print filesystem errors containing private absolute paths.
        detail = str(exc) if isinstance(exc, BaseVerificationError) else "filesystem access failed"
        print(f"Checkpoint verification unavailable: {detail}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
