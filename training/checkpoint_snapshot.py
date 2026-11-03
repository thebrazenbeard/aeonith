"""Source-only native-Linux Qwen checkpoint materialization experiment.

The source directory and each model file are opened without following a
pathname symlink.  Bytes from those exact open file descriptions are copied
into a newly created, descriptor-pinned owner-private directory and checked
against a separately supplied expected-file manifest.  No Transformers
loader is invoked.  This is NOT a host-owned immutable or same-UID-safe
checkpoint, and it does not enable either training optimizer.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from aeonith.private_output import (
    PrivateOutputError, _open_parent_fd, _require_local_posix_mount,
    create_private_directory,
)
from .verify_base import (
    BaseVerificationError, _expected_files, _no_duplicate_keys, _reject_constant,
    _RUNTIME_SUFFIXES, _TOKENIZER_NAMES,
)


MAX_SNAPSHOT_BYTES = 24 * 1024**3
_BLOCK = 1024 * 1024


class CheckpointSnapshotError(ValueError):
    """Refused to create or verify a pinned model-byte snapshot."""


def _parse_manifest(manifest_path: Path, expected_model: str,
                    expected_revision: str) -> tuple[dict[str, dict], str]:
    # The manifest is an operator-provided claim, not a publisher signature.
    try:
        raw = manifest_path.read_bytes()
        if not 0 < len(raw) <= 256 * 1024:
            raise CheckpointSnapshotError("invalid expected-manifest size")
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                              parse_constant=_reject_constant)
        model, revision, expected = _expected_files(manifest)
    except (OSError, ValueError, UnicodeError, TypeError, BaseVerificationError) as exc:
        if isinstance(exc, CheckpointSnapshotError):
            raise
        raise CheckpointSnapshotError("expected manifest is unavailable or invalid") from exc
    if model != expected_model or revision != expected_revision:
        raise CheckpointSnapshotError("manifest does not bind the required model/revision")
    if "config.json" not in expected or not set(expected).intersection(_TOKENIZER_NAMES):
        raise CheckpointSnapshotError("manifest lacks config or tokenizer")
    shards = {name for name in expected if name.endswith(".safetensors")}
    if not shards:
        raise CheckpointSnapshotError("manifest lacks safetensors weights")
    if "model.safetensors.index.json" not in expected and shards != {"model.safetensors"}:
        raise CheckpointSnapshotError("sharded checkpoint needs its index")
    return expected, hashlib.sha256(raw).hexdigest()


def _open_source_dir(source: Path) -> int:
    if (not source.is_absolute() or source.name in {"", ".", ".."}
            or ".." in source.parts):
        raise CheckpointSnapshotError("checkpoint source needs an absolute traversal-free directory")
    try:
        # Walk through the source leaf too: the shared helper rejects both
        # symlinks and Git-checkout markers at every traversed component.
        fd = _open_parent_fd(source)
        try:
            _require_local_posix_mount(fd)
            attrs = os.fstat(fd)
            if (not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != os.geteuid()
                    or attrs.st_mode & 0o022):
                raise CheckpointSnapshotError("source directory owner/write policy unverified")
            return fd
        except BaseException:
            os.close(fd)
            raise
    except (OSError, PrivateOutputError) as exc:
        raise CheckpointSnapshotError("source directory descriptor cannot be qualified") from exc


def _source_file_identity(fd: int, expected_bytes: int) -> tuple[int, int, int, int, int]:
    try:
        _require_local_posix_mount(fd)
        attrs = os.fstat(fd)
    except (OSError, PrivateOutputError) as exc:
        raise CheckpointSnapshotError("checkpoint source file mount or identity unavailable") from exc
    if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
            or attrs.st_mode & 0o022 or attrs.st_nlink != 1 or attrs.st_size != expected_bytes):
        raise CheckpointSnapshotError("checkpoint file type, owner, links, write policy or size refused")
    return attrs.st_dev, attrs.st_ino, attrs.st_size, attrs.st_mtime_ns, attrs.st_ctime_ns


def _copy_one(source_fd: int, destination_fd: int, name: str,
              expected: dict[str, Any]) -> bytes | None:
    """Copy the opened inode; keep small semantic JSON in memory for checks."""
    try:
        infd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                       dir_fd=source_fd)
    except OSError as exc:
        raise CheckpointSnapshotError("checkpoint file cannot be opened without following a link") from exc
    try:
        identity = _source_file_identity(infd, expected["bytes"])
        outfd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600, dir_fd=destination_fd)
        try:
            digest = hashlib.sha256()
            count = 0
            semantic = bytearray() if name in {"config.json", "model.safetensors.index.json"} else None
            while count < expected["bytes"]:
                block = os.pread(infd, min(_BLOCK, expected["bytes"] - count), count)
                if not block:
                    raise CheckpointSnapshotError("short checkpoint source read")
                digest.update(block)
                if semantic is not None:
                    if len(semantic) + len(block) > (2 * 1024 * 1024):
                        raise CheckpointSnapshotError("checkpoint semantic JSON too large")
                    semantic.extend(block)
                data = memoryview(block)
                while data:
                    wrote = os.write(outfd, data)
                    if wrote <= 0:
                        raise CheckpointSnapshotError("checkpoint destination write stalled")
                    data = data[wrote:]
                count += len(block)
            if (count != expected["bytes"] or digest.hexdigest() != expected["sha256"]
                    or _source_file_identity(infd, expected["bytes"]) != identity):
                raise CheckpointSnapshotError("checkpoint source bytes or identity changed")
            attrs = os.fstat(outfd)
            if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                    or stat.S_IMODE(attrs.st_mode) != 0o600 or attrs.st_size != count):
                raise CheckpointSnapshotError("checkpoint destination identity/permissions unverified")
            os.fsync(outfd)
            os.fchmod(outfd, 0o400)
            os.fsync(outfd)
        finally:
            os.close(outfd)
        # Read back the actual destination inode, not merely the bytes we
        # intended to write. Keep the same pinned parent for the reopen.
        checked = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=destination_fd)
        try:
            attrs = os.fstat(checked)
            if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                    or attrs.st_nlink != 1 or stat.S_IMODE(attrs.st_mode) != 0o400
                    or attrs.st_size != expected["bytes"]):
                raise CheckpointSnapshotError("copied checkpoint file identity or mode changed")
            receipt = hashlib.sha256()
            offset = 0
            while offset < expected["bytes"]:
                block = os.pread(checked, min(_BLOCK, expected["bytes"] - offset), offset)
                if not block:
                    raise CheckpointSnapshotError("short copied checkpoint readback")
                receipt.update(block)
                offset += len(block)
            if receipt.hexdigest() != expected["sha256"]:
                raise CheckpointSnapshotError("copied checkpoint output differs from expected bytes")
        finally:
            os.close(checked)
        return bytes(semantic) if semantic is not None else None
    finally:
        os.close(infd)


def _validate_semantics(config_bytes: bytes | None, index_bytes: bytes | None,
                        expected: dict[str, dict]) -> None:
    def parsed(value: bytes | None) -> dict[str, Any]:
        if value is None:
            raise CheckpointSnapshotError("checkpoint semantic JSON missing")
        try:
            data = json.loads(value.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                              parse_constant=_reject_constant)
        except (ValueError, UnicodeError) as exc:
            raise CheckpointSnapshotError("invalid checkpoint semantic JSON") from exc
        if not isinstance(data, dict):
            raise CheckpointSnapshotError("checkpoint semantic JSON is not an object")
        return data

    if parsed(config_bytes).get("model_type") not in {"qwen3_5", "qwen3_5_text"}:
        raise CheckpointSnapshotError("checkpoint configuration is not Qwen3.5")
    weights = {x for x in expected if x.endswith(".safetensors")}
    if index_bytes is None:
        if weights != {"model.safetensors"}:
            raise CheckpointSnapshotError("checkpoint shards require an index")
        return
    mapping = parsed(index_bytes).get("weight_map")
    if not isinstance(mapping, dict) or not mapping:
        raise CheckpointSnapshotError("invalid shard weight map")
    if (any(not isinstance(key, str) or not key or len(key) > 1024
            or not isinstance(name, str) for key, name in mapping.items())
            or set(mapping.values()) != weights):
        raise CheckpointSnapshotError("shard index does not bind exact weight files")


def materialize_verified_snapshot(source: str | os.PathLike[str],
                                  manifest_path: str | os.PathLike[str],
                                  destination: str | os.PathLike[str], *,
                                  expected_model: str, expected_revision: str,
                                  max_total_bytes: int = MAX_SNAPSHOT_BYTES) -> dict[str, Any]:
    """Make an exclusive private copy; preserve incomplete output on error.

    Returns only non-secret checksums/counts. The copy is not authenticated to
    a real publisher and not safe against a malicious same-UID/privileged host
    process. The existing optimizer gate MUST remain closed.
    """
    if sys.platform != "linux" or os.name != "posix":
        raise CheckpointSnapshotError("snapshot requires native Linux POSIX semantics")
    if type(max_total_bytes) is not int or not 0 < max_total_bytes <= MAX_SNAPSHOT_BYTES:
        raise CheckpointSnapshotError("invalid snapshot size budget")
    try:
        expected, manifest_sha = _parse_manifest(Path(manifest_path), expected_model,
                                                 expected_revision)
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, CheckpointSnapshotError):
            raise
        raise CheckpointSnapshotError("expected manifest unavailable") from exc
    total = sum(entry["bytes"] for entry in expected.values())
    if total > max_total_bytes:
        raise CheckpointSnapshotError("expected snapshot exceeds byte budget")
    source_path = Path(source)
    src = _open_source_dir(source_path)
    try:
        source_identity = os.fstat(src)
        names = os.listdir(src)
        if len(names) > 272:
            raise CheckpointSnapshotError("too many source entries")
        for name in names:
            attrs = os.stat(name, dir_fd=src, follow_symlinks=False)
            if not stat.S_ISREG(attrs.st_mode):
                raise CheckpointSnapshotError("source contains a link, directory or special entry")
        runtime = {name for name in names if name.endswith(_RUNTIME_SUFFIXES)}
        if runtime != set(expected):
            raise CheckpointSnapshotError("manifest does not cover exact runtime files")
        try:
            with create_private_directory(destination) as output:
                rootfd = output._directory_fd
                if rootfd is None:
                    raise CheckpointSnapshotError("snapshot output root unexpectedly closed")
                semantic: dict[str, bytes | None] = {}
                for name in sorted(expected):
                    data = _copy_one(src, rootfd, name, expected[name])
                    if data is not None:
                        semantic[name] = data
                _validate_semantics(semantic.get("config.json"),
                                    semantic.get("model.safetensors.index.json"), expected)
                os.fsync(rootfd)
                # Even if an ancestor's lexical path is replaced, all output
                # files were created relative to the same pinned root object.
                owner = os.fstat(rootfd)
                if owner.st_uid != os.geteuid() or stat.S_IMODE(owner.st_mode) != 0o700:
                    raise CheckpointSnapshotError("snapshot root permissions changed")
                # Detect a lexical path silently retargeted while this run
                # held the original root directory handle. Do not confuse a
                # pinned write with a stable future pathname/loader contract.
                destination_attrs = os.stat(destination, follow_symlinks=False)
                if (destination_attrs.st_dev, destination_attrs.st_ino) != (owner.st_dev, owner.st_ino):
                    raise CheckpointSnapshotError("snapshot output path no longer names pinned directory")
                source_attrs = os.stat(source_path, follow_symlinks=False)
                if (source_attrs.st_dev, source_attrs.st_ino) != (source_identity.st_dev, source_identity.st_ino):
                    raise CheckpointSnapshotError("source path changed during snapshot")
        except (OSError, PrivateOutputError) as exc:
            raise CheckpointSnapshotError("private snapshot output creation failed") from exc
    finally:
        os.close(src)
    return {
        "schema_version": "aeonith.model_snapshot_experiment.v1",
        "status": "source_bytes_copied_and_digest_checked_not_training_qualified",
        "model_id_operator_declared": expected_model,
        "revision_operator_declared": expected_revision,
        "expected_manifest_sha256": manifest_sha,
        "files_copied": len(expected),
        "bytes_copied": total,
        "source_bytes_matched_expected": True,
        "publisher_origin_authenticated": False,
        "model_loader_custody_qualified": False,
        "optimizer_authorized": False,
        "limitations": [
            "manifest issuer/publisher origin is not authenticated",
            "same-UID or privileged mutation of snapshot files remains possible",
            "Transformers pathname canonicalization and actual loaded weights are untested",
            "an interrupted destination remains for owner inspection and is never declared complete",
        ],
    }
