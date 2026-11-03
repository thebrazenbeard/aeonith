"""Local, explicit operator review of model-generated synthetic candidates.

This helper only creates a private v2 approval proposal after a person reviews
every record and confirms the exact candidate SHA-256. It does not admit data,
start training, authenticate an identity, or grant publication rights.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import unicodedata
from typing import Iterator, TextIO

from aeonith.private_output import (
    PrivateOutputError, _open_parent_fd, _require_local_posix_mount,
    create_private_directory,
)
from .admit_candidates import (
    AdmissionError, MAX_INPUT_BYTES, SYNTHETIC_EXCLUSION_REASONS,
    _candidate_rows, _no_constants, _no_duplicates, _private_path,
    _synthetic_provenance, _validated_splits,
)


class ReviewAborted(ValueError):
    """No owner approval was written; intervention or qualification is needed."""


def _read_all(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = MAX_INPUT_BYTES + 1
    while remaining > 0:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise ReviewAborted("candidate file size is invalid")
    return raw


@contextmanager
def _pinned_private_candidate(candidate_path: Path) -> Iterator[tuple[dict, str, int, int]]:
    """Read exact private bytes from an owner-only, no-follow native Linux FD."""
    if sys.platform != "linux" or os.name == "nt":
        raise ReviewAborted("private candidate review requires qualified native Linux storage")
    parent_fd = _open_parent_fd(candidate_path.parent)
    file_fd: int | None = None
    try:
        # O_NOFOLLOW rejects symlinks; O_NONBLOCK prevents a raced FIFO/device
        # substitution from blocking the reviewing operator before fstat().
        file_fd = os.open(candidate_path.name, os.O_RDONLY | os.O_NOFOLLOW |
                          os.O_NONBLOCK, dir_fd=parent_fd)
        # The leaf itself could be a bind mount from an unqualified filesystem
        # even when its parent directory resides on native ext4/xfs.
        _require_local_posix_mount(file_fd)
        attrs = os.fstat(file_fd)
        if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                or attrs.st_mode & 0o077 or attrs.st_nlink != 1):
            raise ReviewAborted("candidate must be an owner-only, singly linked regular file")
        raw = _read_all(file_fd)
        try:
            candidate = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                                   parse_constant=_no_constants)
        except (UnicodeError, ValueError) as exc:
            raise ReviewAborted("candidate is not valid strict JSON") from exc
        if not isinstance(candidate, dict):
            raise ReviewAborted("candidate JSON must be an object")
        _candidate_rows(candidate)
        _synthetic_provenance(candidate)
        yield candidate, hashlib.sha256(raw).hexdigest(), parent_fd, file_fd
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def _write(terminal: TextIO, value: str) -> None:
    terminal.write(value)
    terminal.flush()


def _visible_untrusted(value: str) -> str:
    """Render literary text visibly without executing terminal control codes.

    Preserve ordinary Unicode and paragraph breaks, but show C0/C1/DEL,
    bidirectional format overrides/isolates, and Unicode line separators as
    literal code-point escapes. Never alter the underlying candidate bytes.
    """
    rendered: list[str] = []
    for char in value:
        if char == "\n":
            rendered.append("\n")
        elif (unicodedata.category(char).startswith("C") or
              unicodedata.category(char) in {"Zl", "Zp"}):
            rendered.append(f"\\u{ord(char):04x}" if ord(char) <= 0xFFFF
                            else f"\\U{ord(char):08x}")
        else:
            rendered.append(char)
    return "".join(rendered)


def _ask(terminal: TextIO, prompt: str) -> str:
    _write(terminal, prompt)
    answer = terminal.readline()
    if not answer:
        raise ReviewAborted("review ended without complete operator approval")
    value = answer.strip()
    if value.casefold() in {"q", "quit", "abort"}:
        raise ReviewAborted("operator abandoned review; nothing approved")
    return value


def _decision(terminal: TextIO, record: dict, number: int, total: int) -> dict:
    # All private text goes to an explicit local controlling terminal, never
    # stdout/stderr or an ordinary process log unless the operator records it.
    _write(terminal, f"\nRecord {number}/{total} | {record['id']} | "
                     f"{record['split']} | {record['lens']}\n\n"
                     f"PASSAGE:\n{_visible_untrusted(record['passage'])}\n\n"
                     f"PROPOSED CRITIQUE:\n"
                     f"{_visible_untrusted(json.dumps(record['target'], ensure_ascii=False, indent=2))}\n\n")
    choice = _ask(terminal, "Decision [admit/reject/exclude/quit]: ").casefold()
    if choice not in {"admit", "reject", "exclude"}:
        raise ReviewAborted("every record requires one explicit valid decision")
    entry = {
        "id": record["id"], "source_id": record["source_id"],
        "rights_basis": "synthetic_generated", "permission_to_train": choice == "admit",
        "editorial_accepted": False, "permission_to_publish_adapter": False,
        "disposition": choice,
    }
    if choice != "admit":
        reason = _ask(terminal, "Reason [rights_unclear/quality/duplicate/out_of_scope/other]: ")
        if reason not in SYNTHETIC_EXCLUSION_REASONS:
            raise ReviewAborted("a rejected or excluded record needs a valid reason")
        entry["reason_code"] = reason
    return entry


def _unchanged(candidate_path: Path, digest: str, parent_fd: int, file_fd: int) -> bool:
    """Reject source edits/repointing after inspection, before approval is made."""
    original = os.fstat(file_fd)
    present = os.stat(candidate_path.name, dir_fd=parent_fd, follow_symlinks=False)
    return ((original.st_dev, original.st_ino, original.st_uid) ==
            (present.st_dev, present.st_ino, present.st_uid)
            and stat.S_ISREG(present.st_mode) and not present.st_mode & 0o077
            and present.st_nlink == 1
            and hashlib.sha256(_read_all(file_fd)).hexdigest() == digest)


def review_candidates(candidate_path: str | Path, output_dir: str | Path,
                      terminal: TextIO) -> dict[str, object]:
    """Interactively review all examples; write only after exact final consent."""
    try:
        if sys.platform != "linux" or os.name == "nt":
            raise ReviewAborted("qualified native Linux private storage is required")
        candidate_file = _private_path(candidate_path, exists=True, label="candidate")
        destination = _private_path(output_dir, exists=False, label="approval output")
        # Qualify output parent *before* showing a private candidate. The
        # creation itself is performed again with a fresh pinned parent FD.
        output_parent_fd = _open_parent_fd(destination.parent)
        os.close(output_parent_fd)
        with _pinned_private_candidate(candidate_file) as (candidate, digest, parent_fd, file_fd):
            records = candidate["examples"]
            _write(terminal, "MODEL-GENERATED SYNTHETIC CANDIDATE REVIEW\n"
                             "No publication permission; approval is only for a later private local pilot.\n"
                             "No choices are preapproved, and quitting writes nothing.\n"
                             f"Candidate SHA-256: {digest}\n"
                             f"Total records: {len(records)}\n")
            decisions = [_decision(terminal, row, index, len(records))
                         for index, row in enumerate(records, start=1)]
            tally = Counter(item["disposition"] for item in decisions)
            kept = Counter(row["split"] for row, decision in zip(records, decisions)
                           if decision["disposition"] == "admit")
            _write(terminal, f"\nDecisions: {dict(tally)}; admitted by split: {dict(kept)}\n"
                             "A later corpus audit and runtime qualification remain mandatory.\n")
            identity = _ask(terminal, "Your real operator identity (self-attested): ")
            confirmation_sha = _ask(terminal, "Type the COMPLETE candidate SHA-256: ")
            confirmation_phrase = _ask(terminal, "Type APPROVE_PRIVATE_LOCAL_TRAINING to confirm: ")
            if (confirmation_sha != digest or confirmation_phrase != "APPROVE_PRIVATE_LOCAL_TRAINING"):
                raise ReviewAborted("exact candidate approval was not confirmed")
            approval = {
                "schema_version": "aeonith.candidate_synthetic_admission.v2",
                "candidate_sha256": digest,
                "approval_status": "APPROVED_MODEL_GENERATED_PRIVATE_LOCAL_TRAINING",
                "permission_to_train": True,
                "operator_decision": {
                    "identity": identity,
                    "decision": "approve_exact_model_generated_private_training",
                    "attested_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "candidate_sha256": digest,
                },
                "records": decisions,
            }
            _validated_splits(candidate, approval, digest)
            if not _unchanged(candidate_file, digest, parent_fd, file_fd):
                raise ReviewAborted("candidate identity or exact bytes changed during review")
            serialized = json.dumps(approval, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            with create_private_directory(destination) as writer:
                writer.write_text("approval.json", serialized)
            _write(terminal, "Private approval created. Verify with training.admit_candidates "
                             "before separate corpus audit; this did NOT start training.\n")
            return {"candidate_sha256": digest, "approval_path": str(destination / "approval.json"),
                    "record_disposition_counts": dict(tally)}
    except (AdmissionError, PrivateOutputError, OSError) as exc:
        raise ReviewAborted("private candidate review or output custody was not qualified") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, help="Private native Linux candidates.json path")
    parser.add_argument("--output", required=True, help="NEW private directory outside all Git checkouts")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "linux" or os.name == "nt":
            raise ReviewAborted("owner review currently requires native Linux private output")
        # Unlike stdout, the controlling TTY cannot silently be redirected to
        # a pipeline/log file. Terminal screen capture remains operator risk.
        with open("/dev/tty", "r+", encoding="utf-8") as terminal:
            review_candidates(args.candidates, args.output, terminal)
    except (ReviewAborted, OSError):
        print("Review cancelled or private custody unqualified; no approval granted.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
