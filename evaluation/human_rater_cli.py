"""Offline, private human-rating collector and study assembler.

No model calls and no automatic literary scoring. Pair/manuscript text and
critique prose are **never** printed: a consenting reviewer reads the existing
owner-private blind-pair file in a trusted viewer, then enters ratings here.
The collector writes only an exact-display-bound private rubric. Distinct
pseudonyms do not authenticate distinct humans or establish independence.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable

from aeonith.private_output import PrivateOutputError, _open_parent_fd, MAX_PRIVATE_FILE_BYTES
from .quality_eval import (
    ANNOTATION_SCHEMA, DIMENSIONS, STUDY_SCHEMA, _preflight_private_output,
    _validated_pair_id, _write_json_exclusive, bind_annotation_to_display,
    digest, summarize_study,
)

MANIFEST_SCHEMA = "aeonith.human_study_file_manifest.v1"
MAX_INPUT_FILE_BYTES = 4_000_000
MAX_STUDY_INPUT_BYTES = 16_000_000
MAX_STUDY_PAIRS = 200
MAX_RATERS_PER_PAIR = 40
MAX_STUDY_ANNOTATIONS = 4000
TRUSTED_LOCAL_LINUX_FS = frozenset({
    "ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "zfs", "tmpfs", "overlay",
})
DIMENSION_GUIDANCE = {
    "textual_accuracy": "claims and quoted evidence actually fit the supplied work",
    "lens_distinctness": "this lens contributes an interpretation beyond a repeated template",
    "critical_depth": "insight and reasoning beyond plot summary or generic praise",
    "calibration": "uncertainty, limits and alternative readings are represented fairly",
    "actionability": "specific feedback would help an author revise or understand the work",
    "synthesis": "the critique integrates its observations coherently",
}


class ReviewerSessionError(ValueError):
    """Private study cannot be safely collected, assembled, or completed."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewerSessionError("duplicate JSON fields are not allowed")
        result[key] = value
    return result


def _linux_mount_type(path: Path) -> str | None:
    """Conservative Linux mount classification; paths never become log text."""
    if not sys.platform.startswith("linux"):
        return None
    selected = (-1, None)
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as handle:
            for line in handle:
                before, after = line.split(" - ", 1)
                fields = before.split()
                if len(fields) < 5:
                    continue
                mountpoint = re.sub(r"\\([0-7]{3})",
                                    lambda match: chr(int(match.group(1), 8)), fields[4])
                mountpoint = os.path.normpath(mountpoint)
                if (path == Path(mountpoint) or Path(mountpoint) in path.parents):
                    if len(mountpoint) > selected[0]:
                        selected = (len(mountpoint), after.split()[0])
    except (OSError, UnicodeError, ValueError, IndexError):
        return None
    return selected[1]


def _require_native_private_filesystem(path: str | os.PathLike[str]) -> None:
    """Reject WSL DrvFS/9p and remote/unknown mounts despite emulated chmod."""
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw:
        raise ReviewerSessionError("invalid private filesystem path")
    destination = Path(os.path.abspath(os.path.expanduser(raw)))
    fstype = _linux_mount_type(destination.parent)
    if fstype not in TRUSTED_LOCAL_LINUX_FS:
        raise ReviewerSessionError("private study requires a supported local Linux-native filesystem")


def _read_private_json_bounded(path: str | os.PathLike[str], *, budget: int) -> tuple[dict, int]:
    """Read a bounded, owner-only JSON file via a pinned POSIX parent.

    Windows private-file custody has not been qualified; refuse it. No
    symlinked ancestors, final symlinks, Git paths or group-readable files.
    """
    if os.name != "posix":
        raise ReviewerSessionError("private study input requires qualified POSIX/WSL file custody")
    try:
        _require_native_private_filesystem(path)
        raw_path = os.fspath(path)
        if (not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path
                or "://" in raw_path or ".." in Path(raw_path).parts):
            raise ReviewerSessionError("private input path is invalid")
        target = Path(os.path.abspath(os.path.expanduser(raw_path)))
        if target.name in {"", ".", "..", ".git"}:
            raise ReviewerSessionError("private input filename is invalid")
        parent_fd = _open_parent_fd(target.parent)
        try:
            fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                attrs = os.fstat(fd)
                if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                        or attrs.st_mode & 0o077
                        or not 0 < attrs.st_size <= min(MAX_INPUT_FILE_BYTES, budget)):
                    raise ReviewerSessionError("private study input access or size is not qualified")
                with os.fdopen(os.dup(fd), "rb") as stream:
                    raw = stream.read(min(MAX_INPUT_FILE_BYTES, budget) + 1)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
        if not 0 < len(raw) <= min(MAX_INPUT_FILE_BYTES, budget):
            raise ReviewerSessionError("private study input is empty or oversized")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ReviewerSessionError("non-finite JSON values are forbidden")))
        if not isinstance(data, dict):
            raise ReviewerSessionError("private study input must be a JSON object")
        return data, len(raw)
    except (OSError, UnicodeError, ValueError, RecursionError, PrivateOutputError) as exc:
        raise ReviewerSessionError("private study input failed safe validation") from exc


def read_private_json(path: str | os.PathLike[str]) -> dict:
    """Public bounded reader used by an individual rater, never a bulk loop."""
    return _read_private_json_bounded(path, budget=MAX_INPUT_FILE_BYTES)[0]


def collect_private_annotation(
    pair: dict,
    *,
    ask: Callable[[str], str],
    emit: Callable[[str], None],
) -> dict:
    """Human-authored rubric for a privately viewed blind pair; no source display.

    `ask` and `emit` are injected only to test the user-driven workflow.
    Calling this function with synthetic scripted answers is a TEST, not a
    verified human study. The executable CLI enforces interactive TTY usage.
    """
    try:
        pair_id = _validated_pair_id(pair)
        display_sha = digest(pair)
        emit("Private A/B comparison. Open the pair JSON in a trusted local viewer.")
        emit("Keep assignment keys, screenshots, transcription tools, and terminal logging away from raters.")
        emit("Pair ID: " + pair_id)
        emit("Exact display SHA-256: " + display_sha)
        if ask("After privately reading this exact pair, type I REVIEWED to continue: ").strip() != "I REVIEWED":
            raise ReviewerSessionError("rater did not confirm the private pair was reviewed")
        nickname = ask("Private reviewer pseudonym (not proof of identity): ").strip()
        dimensions: dict[str, dict[str, int]] = {}
        emit("Score each critique independently: 0=weak/misleading, 1=mixed, 2=strong/evidence-grounded.")
        for dimension in DIMENSIONS:
            emit(f"{dimension}: {DIMENSION_GUIDANCE[dimension]}")
            scores: dict[str, int] = {}
            for side in ("A", "B"):
                raw = ask(f"{dimension}, {side} [0/1/2]: ").strip()
                if raw not in {"0", "1", "2"}:
                    raise ReviewerSessionError("invalid dimension rating; no annotation saved")
                scores[side] = int(raw)
            dimensions[dimension] = scores
        preference = ask("Overall preference [A/B/tie/incomparable]: ").strip()
        rationale = ask("Evidence-based rationale (20..4000 characters, one line): ").strip()
        annotation = {
            "schema_version": ANNOTATION_SCHEMA, "pair_id": pair_id,
            "reviewer_pseudonym": nickname, "dimensions": dimensions,
            "preference": preference, "rationale": rationale,
        }
        return bind_annotation_to_display(annotation, pair)
    except (TypeError, ValueError, StopIteration, EOFError) as exc:
        raise ReviewerSessionError("private annotation is incomplete or invalid; no output saved") from exc


def rate_private_pair(
    pair_path: str | os.PathLike[str], output_path: str | os.PathLike[str],
    *, ask: Callable[[str], str], emit: Callable[[str], None],
) -> dict[str, Any]:
    """Persist a genuinely user-entered bound rubric, never overwritten."""
    try:
        _require_native_private_filesystem(output_path)
        _preflight_private_output(os.fspath(output_path))
        pair = read_private_json(pair_path)
        bound = collect_private_annotation(pair, ask=ask, emit=emit)
        data = json.dumps(bound, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(data.encode("utf-8")) > MAX_PRIVATE_FILE_BYTES:
            raise ReviewerSessionError("private annotation too large")
        _write_json_exclusive(os.fspath(output_path), bound)
        return {
            "status": "OPERATOR_DECLARED_ANNOTATION_SAVED",
            "pair_id": bound["annotation"]["pair_id"],
            "display_sha256": bound["display_sha256"],
            "human_identity_independently_verified": False,
            "semantic_quality": "UNASSESSED",
        }
    except (TypeError, ValueError, RecursionError, OSError, PrivateOutputError) as exc:
        raise ReviewerSessionError("private annotation could not be saved") from exc


def assemble_study(manifest_path: str | os.PathLike[str],
                   output_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Assemble real submitted rubric files into a private, validated bundle.

    No source texts, rationales or pseudonyms appear in the returned summary.
    Input is a caller-owned file-path list, not a signature/identity record.
    """
    try:
        _require_native_private_filesystem(output_path)
        _preflight_private_output(os.fspath(output_path))
        manifest, manifest_bytes = _read_private_json_bounded(
            manifest_path, budget=MAX_INPUT_FILE_BYTES
        )
        if set(manifest) != {"schema_version", "records"} or manifest["schema_version"] != MANIFEST_SCHEMA:
            raise ReviewerSessionError("invalid study assembly manifest")
        items = manifest["records"]
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_STUDY_PAIRS:
            raise ReviewerSessionError("invalid number of study records")
        # Reject a request for unbounded reads before touching referenced
        # private files. Individual 4MB caps alone would permit >32GB input.
        total_refs = 0
        for item in items:
            if (not isinstance(item, dict) or set(item) != {"pair_file", "bound_annotation_files"}
                    or not isinstance(item["pair_file"], str)
                    or not isinstance(item["bound_annotation_files"], list)
                    or len(item["bound_annotation_files"]) > MAX_RATERS_PER_PAIR
                    or any(not isinstance(value, str) for value in item["bound_annotation_files"])):
                raise ReviewerSessionError("invalid study assembly record")
            total_refs += len(item["bound_annotation_files"])
        if total_refs > MAX_STUDY_ANNOTATIONS:
            raise ReviewerSessionError("study assembly annotation count exceeds bound")
        budget = MAX_STUDY_INPUT_BYTES - manifest_bytes
        records: list[dict[str, Any]] = []
        for item in items:
            pair, consumed = _read_private_json_bounded(item["pair_file"], budget=budget)
            budget -= consumed
            annotations = []
            for path in item["bound_annotation_files"]:
                bound, consumed = _read_private_json_bounded(path, budget=budget)
                budget -= consumed
                annotations.append(bound)
            records.append({"pair": pair, "annotations": annotations})
        study = {"schema_version": STUDY_SCHEMA, "records": records}
        summary = summarize_study(study)
        data = json.dumps(study, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(data.encode("utf-8")) > MAX_PRIVATE_FILE_BYTES:
            raise ReviewerSessionError("assembled study exceeds private file limit")
        _write_json_exclusive(os.fspath(output_path), study)
        return {
            "status": "OPERATOR_DECLARED_STUDY_ASSEMBLED",
            "pair_count": summary["pair_count"],
            "rated_pair_count": summary["rated_pair_count"],
            "total_annotations": summary["total_annotations"],
            "human_independence_verified": False,
            "model_execution_authenticated": False,
            "semantic_quality": "UNASSESSED",
        }
    except (TypeError, ValueError, RecursionError, OSError, UnicodeError, PrivateOutputError) as exc:
        raise ReviewerSessionError("private study assembly failed safe validation") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline private human rating collector (no model calls)")
    commands = parser.add_subparsers(dest="command", required=True)
    rate = commands.add_parser("rate", help="Interactively record one human blind-pair rubric")
    rate.add_argument("--pair", type=Path, required=True)
    rate.add_argument("--out", type=Path, required=True)
    bundle = commands.add_parser("assemble", help="Assemble privately completed blind rubrics")
    bundle.add_argument("--manifest", type=Path, required=True)
    bundle.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "rate" and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        print("Private human rating requires a non-logged interactive terminal", file=sys.stderr)
        return 2
    try:
        if args.command == "rate":
            result = rate_private_pair(args.pair, args.out, ask=input, emit=print)
        else:
            result = assemble_study(args.manifest, args.out)
    except ReviewerSessionError:
        print("Private human study unavailable; inspect permissions, input and consent locally", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
