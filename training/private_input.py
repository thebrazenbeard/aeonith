"""Experimental, read-only Linux file-descriptor custody for private train input.

An opened input is read through the same kernel file descriptor whose owner,
mode, mount and inode were checked. This defeats ancestor pathname replacement
for this read. It is *not* wired into Trainer and is no protection against
malicious same-UID code, privileged host access, or mutable input later re-read
by a separate framework from a pathname.
"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat
import sys
from typing import Self

from aeonith.private_output import (
    PrivateOutputError, _open_parent_fd, _require_local_posix_mount,
)


class PrivateInputError(ValueError):
    """This file was not safely admitted to a private read snapshot."""


class PinnedPrivateInput:
    """Own a regular private file handle and read only its exact opened inode.

    The caller must retain this object open for each read and avoid path-based
    reopens after verification. `read_bytes` returns bounded private data only
    in memory; `fingerprint` returns only a digest and byte count.
    """

    def __init__(self, fd: int, max_bytes: int) -> None:
        self._fd: int | None = None
        if sys.platform != "linux" or os.name != "posix":
            raise PrivateInputError("verified private input requires native Linux filesystem semantics")
        if type(max_bytes) is not int or not 0 < max_bytes <= 64 * 1024 * 1024:
            raise PrivateInputError("invalid bounded private-input size limit")
        self._identity = self._checked_identity(fd)
        if self._identity[2] > max_bytes:
            raise PrivateInputError("private input exceeds its read limit")
        self._limit = max_bytes
        self._fd = fd

    @staticmethod
    def _checked_identity(fd: int) -> tuple[int, int, int, int, int]:
        try:
            _require_local_posix_mount(fd)
            attrs = os.fstat(fd)
        except (PrivateOutputError, OSError) as exc:
            raise PrivateInputError("private input mount or descriptor cannot be verified") from exc
        if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                or stat.S_IMODE(attrs.st_mode) & 0o077 or attrs.st_nlink != 1):
            raise PrivateInputError("private input must be a single-linked owner-only regular file")
        return (attrs.st_dev, attrs.st_ino, attrs.st_size, attrs.st_mtime_ns, attrs.st_ctime_ns)

    @classmethod
    def open(cls, value: str | os.PathLike[str], *, max_bytes: int) -> Self:
        raw = os.fspath(value)
        if (not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//")
                or "\x00" in raw or ".." in Path(raw).parts or Path(raw).name in {"", ".", ".."}):
            raise PrivateInputError("private input must be an absolute traversal-free local path")
        path = Path(raw)
        if not path.parent.is_absolute():
            raise PrivateInputError("invalid private input parent")
        try:
            parent = _open_parent_fd(path.parent)
        except (PrivateOutputError, OSError) as exc:
            raise PrivateInputError("private input ancestor custody cannot be verified") from exc
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(path.name, flags, dir_fd=parent)
        except OSError as exc:
            raise PrivateInputError("private input could not be opened without following a link") from exc
        finally:
            os.close(parent)
        try:
            return cls(fd, max_bytes)
        except BaseException:
            os.close(fd)
            raise

    def read_bytes(self) -> bytes:
        if self._fd is None:
            raise PrivateInputError("private input descriptor has been closed")
        if self._checked_identity(self._fd) != self._identity:
            raise PrivateInputError("private input identity changed before read")
        try:
            chunks = []
            count = 0
            while True:
                # Use explicit offsets rather than the open-file-description
                # seek position shared with dup() and inherited descriptors.
                # Another consumer may seek independently without corrupting
                # this bounded snapshot's byte order.
                block = os.pread(self._fd, min(1024 * 1024, self._limit - count + 1), count)
                if not block:
                    break
                count += len(block)
                if count > self._limit:
                    raise PrivateInputError("private input changed beyond its read limit")
                chunks.append(block)
        except OSError as exc:
            raise PrivateInputError("private input descriptor read failed") from exc
        if self._checked_identity(self._fd) != self._identity or count != self._identity[2]:
            raise PrivateInputError("private input changed during read")
        return b"".join(chunks)

    def fingerprint(self) -> dict[str, str | int]:
        data = self.read_bytes()
        return {"bytes": len(data), "sha256": sha256(data).hexdigest()}

    def close(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
