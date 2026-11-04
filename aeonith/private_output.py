"""Conservative private-output directory boundary for local artifacts.

This is a reusable, opt-in building block; existing writers must be migrated
and independently qualified before claiming their outputs use this boundary.
On POSIX it pins directory descriptors, avoiding pathname redirection during
creation and writes. Windows deliberately fails closed until a verified parent
ACL and equivalent handle-relative writing contract are implemented.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
from typing import Self


class PrivateOutputError(ValueError):
    """A private output location or write could not be safely established."""


MAX_PRIVATE_FILE_BYTES = 64_000_000

# POSIX owner/mode bits reported by WSL DrvFS/9p can be emulated and do not
# establish the Windows-side effective ACL. Limit this helper to known native
# Linux filesystem families; this is still not a same-UID or host-root sandbox.
_LOCAL_LINUX_FILESYSTEMS = frozenset({
    "ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "tmpfs", "overlay", "zfs",
})


def _is_windows() -> bool:
    return os.name == "nt"


def _parse_linux_mount_type(fdinfo: str, mountinfo: str) -> str:
    """Match the kernel's exact open-file mount ID, not a mutable path prefix."""
    mount_ids = [line.split(":", 1)[1].strip() for line in fdinfo.splitlines()
                 if line.startswith("mnt_id:")]
    if len(mount_ids) != 1 or not mount_ids[0].isdigit():
        raise PrivateOutputError("private output mount identity is unavailable")
    for line in mountinfo.splitlines():
        leading, separator, trailing = line.partition(" - ")
        if not separator:
            continue
        fields = leading.split()
        if fields and fields[0] == mount_ids[0]:
            details = trailing.split()
            if details:
                return details[0]
    raise PrivateOutputError("private output mount identity was not found")


def _linux_mount_type_for_fd(fd: int) -> str:
    """Read a kernel-issued mount ID for the pinned directory descriptor."""
    try:
        fdinfo = Path(f"/proc/self/fdinfo/{fd}").read_text(encoding="utf-8")
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PrivateOutputError("private output mount identity cannot be verified") from exc
    return _parse_linux_mount_type(fdinfo, mountinfo)


def _require_local_posix_mount(fd: int) -> None:
    if sys.platform != "linux":
        raise PrivateOutputError("private output requires a verified local Linux filesystem")
    if _linux_mount_type_for_fd(fd) not in _LOCAL_LINUX_FILESYSTEMS:
        raise PrivateOutputError("private output filesystem is not qualified for POSIX privacy")


def _open_parent_fd(path: Path) -> int:
    """Walk from filesystem root without following path-component symlinks."""
    if not path.is_absolute() or not path.parts or path.parts[0] != "/":
        raise PrivateOutputError("an absolute local POSIX directory is required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        _require_local_posix_mount(fd)
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            _require_local_posix_mount(fd)
            attrs = os.fstat(fd)
            if not stat.S_ISDIR(attrs.st_mode):
                raise PrivateOutputError("private output parent is not a directory")
            # A sticky bit prevents peers from replacing another user's
            # entries, but *the directory owner* may still rename or remove
            # any child. Only a root-owned or self-owned sticky writable
            # ancestor is an acceptable shared-temp boundary (e.g. /tmp).
            if (attrs.st_mode & 0o022 and
                    (not attrs.st_mode & stat.S_ISVTX or
                     attrs.st_uid not in (0, os.geteuid()))):
                raise PrivateOutputError("private output parent permits unsafe replacement")
            try:
                marker = os.stat(".git", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISLNK(marker.st_mode):
                    raise PrivateOutputError("private output cannot traverse a Git marker link")
                if stat.S_ISDIR(marker.st_mode):
                    marker_fd = os.open(".git", flags, dir_fd=fd)
                    try:
                        try:
                            os.stat("HEAD", dir_fd=marker_fd, follow_symlinks=False)
                        except FileNotFoundError:
                            pass  # Empty unrelated .git directory is not a checkout.
                        else:
                            raise PrivateOutputError("private output cannot be inside a Git checkout")
                    finally:
                        os.close(marker_fd)
                elif stat.S_ISREG(marker.st_mode):
                    marker_fd = os.open(".git", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        if os.read(marker_fd, 7) == b"gitdir:":
                            raise PrivateOutputError("private output cannot be inside a Git checkout")
                    finally:
                        os.close(marker_fd)
            # Bare Git repositories have no .git child, but are just as unsafe.
            try:
                bare_head = os.stat("HEAD", dir_fd=fd, follow_symlinks=False)
                bare_refs = os.stat("refs", dir_fd=fd, follow_symlinks=False)
                bare_objects = os.stat("objects", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (stat.S_ISREG(bare_head.st_mode)
                        and stat.S_ISDIR(bare_refs.st_mode)
                        and stat.S_ISDIR(bare_objects.st_mode)):
                    raise PrivateOutputError("private output cannot be inside a bare Git repository")
        return fd
    except BaseException:
        os.close(fd)
        raise


class PrivateOutputDirectory:
    """Descriptor-pinned private output created exclusively for one run.

    The directory survives closing this object; no unexpected cleanup or
    overwrite occurs. Use as a context manager to close the pinned handle.
    """

    def __init__(self, path: Path, directory_fd: int) -> None:
        # Some callers create child directories directly beneath an existing
        # pinned parent. Recheck the exact new FD here, rather than relying on
        # every caller to remember the mount and ownership invariants.
        if _is_windows():
            raise PrivateOutputError("Windows private output ACL boundary is not yet qualified")
        _require_local_posix_mount(directory_fd)
        attrs = os.fstat(directory_fd)
        if (not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != os.geteuid()
                or attrs.st_mode & 0o077):
            raise PrivateOutputError("private output directory access controls are not verified")
        self.path = path
        self._directory_fd: int | None = directory_fd

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        fd, self._directory_fd = self._directory_fd, None
        if fd is not None:
            os.close(fd)

    def write_bytes(self, name: str, content: bytes) -> None:
        """Create one new, size-bounded, private regular file atomically."""
        if self._directory_fd is None:
            raise PrivateOutputError("private output directory is closed")
        if (not isinstance(name, str) or not name or name in {".", "..", ".git"}
                or "/" in name or "\\" in name or "\x00" in name):
            raise PrivateOutputError("private output filename must be a simple basename")
        if not isinstance(content, bytes) or len(content) > MAX_PRIVATE_FILE_BYTES:
            raise PrivateOutputError("private output content must be bounded bytes")

        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=self._directory_fd,
        )
        try:
            attrs = os.fstat(fd)
            if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                    or attrs.st_mode & 0o077):
                raise PrivateOutputError("private file access controls are not verified")
            view = memoryview(content)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise PrivateOutputError("private file write did not progress")
                view = view[count:]
            os.fsync(fd)
        finally:
            os.close(fd)

    def write_text(self, name: str, content: str) -> None:
        if not isinstance(content, str):
            raise PrivateOutputError("private output text must be a string")
        self.write_bytes(name, content.encode("utf-8"))


def reserve_private_file(value: str | os.PathLike[str]) -> int:
    """Reserve an exclusive, descriptor-pinned private file before inference.

    The caller owns the returned descriptor and must close it. Windows fails
    closed until its anti-reparse and owner-DACL boundary is qualified.
    """
    if _is_windows():
        raise PrivateOutputError("Windows private output ACL boundary is not yet qualified")
    if not all(hasattr(os, attr) for attr in ("O_DIRECTORY", "O_NOFOLLOW", "geteuid")):
        raise PrivateOutputError("required POSIX handle-based protections are unavailable")
    text = os.fspath(value)
    if (not isinstance(text, str) or not text or "\x00" in text or "://" in text
            or text.startswith(("\\", "//")) or ".." in Path(text).parts):
        raise PrivateOutputError("private output file path is invalid")
    destination = Path(os.path.abspath(os.path.expanduser(text)))
    if destination.name in {"", ".", "..", ".git"}:
        raise PrivateOutputError("private output filename is invalid")

    parent_fd = _open_parent_fd(destination.parent)
    try:
        fd = os.open(
            destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=parent_fd,
        )
        try:
            attrs = os.fstat(fd)
            if (not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.geteuid()
                    or attrs.st_mode & 0o077):
                raise PrivateOutputError("private file access controls are not verified")
            return fd
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(parent_fd)


def create_private_directory(value: str | os.PathLike[str]) -> PrivateOutputDirectory:
    """Exclusively create a new private directory and return its pinned handle.

    Windows is refused even on Python 3.13: private *directory creation* is
    available there, but this module has not independently verified parent
    DACL safety and an anti-reparse, handle-relative file-writing boundary.
    Calling code must not interpret this as a Windows host qualification.
    """
    if _is_windows():
        raise PrivateOutputError("Windows private output ACL boundary is not yet qualified")
    if not all(hasattr(os, attr) for attr in ("O_DIRECTORY", "O_NOFOLLOW", "geteuid")):
        raise PrivateOutputError("required POSIX handle-based protections are unavailable")
    value = os.fspath(value)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PrivateOutputError("private output directory path is invalid")
    destination = Path(os.path.abspath(os.path.expanduser(value)))
    if destination.name in {"", ".", "..", ".git"}:
        raise PrivateOutputError("private output directory name is invalid")

    parent_fd = _open_parent_fd(destination.parent)
    try:
        os.mkdir(destination.name, 0o700, dir_fd=parent_fd)
        directory_fd = os.open(
            destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        try:
            _require_local_posix_mount(directory_fd)
            attrs = os.fstat(directory_fd)
            if (not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != os.geteuid()
                    or attrs.st_mode & 0o077):
                raise PrivateOutputError("private directory access controls are not verified")
            return PrivateOutputDirectory(destination, directory_fd)
        except BaseException:
            os.close(directory_fd)
            raise
    finally:
        os.close(parent_fd)
