"""Bounded CPython file-I/O observation for a future local trainer pilot.

This is a falsifier, NOT a filesystem sandbox or training authorization.
Python audit events do not cover arbitrary native/descriptor writes; absence
of an observed external path cannot establish private-output custody.
"""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import sys
from typing import Any

SCHEMA = "aeonith.experimental.trainer_io_observation.v1"
MAX_OBSERVED_EVENTS = 4096
_WRITE_FLAGS = (
    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
)
_MUTATION_EVENTS = frozenset({
    "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.chmod",
    "os.chown", "os.link", "os.symlink", "os.truncate", "os.utime",
})
# CPython os.* audit-event argument indexes for an optional dir_fd. A path
# relative to a supplied fd is not relative to process cwd, and MUST NOT be
# described as inside the private root by a lexical abspath() calculation.
_DIR_FD_INDEX = {
    "os.mkdir": 2, "os.remove": 1, "os.rmdir": 1,
    "os.chmod": 2, "os.chown": 3, "os.utime": 3,
}
_SOURCE_DESTINATION_EVENTS = frozenset({"os.rename", "os.link"})


class PythonTrainerIOObservation:
    """Observe event categories without saving filenames or manuscript text.

    Use only in a disposable, trusted Python process. Hooks added with
    ``sys.addaudithook`` persist until process exit and are not a security
    boundary. The object deactivates its hook when the context exits.
    """

    def __init__(self, expected_private_root: str | os.PathLike[str]) -> None:
        raw = os.fspath(expected_private_root)
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ValueError("expected private root must be a local path")
        self._root = os.path.abspath(raw)
        self._active = False
        self._entered = False
        self._counts: Counter[str] = Counter()
        self._scopes: Counter[str] = Counter()
        self._source_scopes: Counter[str] = Counter()
        self._observed = 0
        self._overflow = False

    @staticmethod
    def _is_write_open(args: tuple[Any, ...]) -> bool:
        if len(args) < 3:
            return False
        mode, flags = args[1], args[2]
        return bool(
            (isinstance(mode, str) and any(token in mode for token in "wax+"))
            or (isinstance(flags, int) and flags & _WRITE_FLAGS)
        )

    def _scope(self, path: Any, dir_fd: Any = None) -> str:
        try:
            if not isinstance(path, (str, bytes, os.PathLike)):
                return "unknown_descriptor_or_nonpath"
            # This is intentionally LEXICAL evidence. A symlink, mount alias,
            # rename, or native write can defeat it; never use to authorize IO.
            raw = os.fspath(path)
            if isinstance(raw, bytes):
                return "unknown_descriptor_or_nonpath"
            if not os.path.isabs(raw) and dir_fd not in (None, -1):
                return "unknown_dirfd_relative"
            candidate = os.path.abspath(raw)
            return ("lexically_within_expected_root" if
                    os.path.commonpath((self._root, candidate)) == self._root
                    else "outside_expected_root")
        except (OSError, ValueError, TypeError):
            return "unknown_descriptor_or_nonpath"

    @staticmethod
    def _impact_paths(event: str, args: tuple[Any, ...]) -> tuple[tuple[str, Any, Any], ...]:
        """Return the write destination and any source mutated/read.

        The source of os.symlink is only link-target text, not a write to that
        target. For os.rename, both entries change; for os.link, the target
        entry is created and the source is observed separately.
        """
        if not args:
            return (("destination", None, None),)
        if event in _SOURCE_DESTINATION_EVENTS:
            return (
                ("destination", args[1] if len(args) > 1 else None,
                 args[3] if len(args) > 3 else None),
                ("source", args[0], args[2] if len(args) > 2 else None),
            )
        if event == "os.symlink":
            return (("destination", args[1] if len(args) > 1 else None,
                     args[2] if len(args) > 2 else None),)
        pos = _DIR_FD_INDEX.get(event)
        return (("destination", args[0],
                 args[pos] if pos is not None and len(args) > pos else None),)

    def _hook(self, event: str, args: tuple[Any, ...]) -> None:
        if not self._active:
            return
        category = ""
        if event == "open" and self._is_write_open(args):
            category = "open_for_write"
        elif event in _MUTATION_EVENTS:
            category = event
        if not category:
            return
        self._observed += 1
        if self._observed > MAX_OBSERVED_EVENTS:
            self._overflow = True
            return
        self._counts[category] += 1
        for role, path, dir_fd in self._impact_paths(event, args):
            scope = self._scope(path, dir_fd)
            if role == "source":
                self._source_scopes[scope] += 1
            else:
                self._scopes[scope] += 1

    def __enter__(self) -> "PythonTrainerIOObservation":
        if self._entered:
            raise RuntimeError("file-I/O observation cannot be reused")
        self._entered = True
        # This itself is an audit event and may be suppressed by an existing
        # hostile hook. No meaningful proof follows from a silent registration.
        sys.addaudithook(self._hook)
        self._active = True
        return self

    def __exit__(self, _type: Any, _value: Any, _tb: Any) -> None:
        self._active = False

    def receipt(self) -> dict[str, Any]:
        if self._active or not self._entered:
            raise RuntimeError("finish file-I/O observation before reading receipt")
        return {
            "schema_version": SCHEMA,
            "status": "OBSERVATION_ONLY_NOT_SECURITY_QUALIFIED",
            "observed_event_count": self._observed,
            "stored_event_limit": MAX_OBSERVED_EVENTS,
            "event_limit_exceeded": self._overflow,
            "event_category_counts": dict(sorted(self._counts.items())),
            # Exactly one destination classification per stored event. For
            # rename/link, the additional source operand has separate counts.
            "lexical_scope_counts": dict(sorted(self._scopes.items())),
            "source_operand_scope_counts": dict(sorted(self._source_scopes.items())),
            "framework_execution_authenticated": False,
            "trainer_output_custody_qualified": False,
            "absence_of_external_writes_proven": False,
            "limitations": [
                "Python audit hooks are not a sandbox and can be bypassed by native code.",
                "Existing file descriptors can be written without a new open event.",
                "Directory-fd-relative paths have unknown custody without a resolved pinned fd.",
                "Link target text is not proof of where future writes through that link land.",
                "Lexical paths do not prove directory/ACL custody under rename or reparse races.",
                "Subprocesses require separate instrumentation and host-owned supervision.",
            ],
        }
