"""Prototype Linux output custody for future local optimizer qualification.

This is **not** wired into train_lora. Trainer/PEFT path canonicalization,
subprocess behavior and genuine optimizer writes are still unqualified.
The training launch gate must remain closed until those integrations are tested.

For same-process, literal pathname operations on Linux, /proc/self/fd/N
identifies an opened directory object, not the user's mutable spelling of its
ancestors. The descriptors remain open for the whole broker context.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
from typing import Self

from aeonith.private_output import (
    PrivateOutputDirectory, PrivateOutputError, create_private_directory,
)


class PinnedTrainingArtifacts:
    """Own one new private root, pinned runtime/adapter dirs and a receipt writer.

    Do not serialize its procfs paths, pass them to subprocesses, or retain
    them after broker.close(). They refer to file descriptors in *this
    process*; a consumer that calls realpath or reuses a cached path after
    descriptor-number recycling can defeat the intended pinning. In
    particular, this class does not authorize training, publication or a
    model-quality claim.
    """

    def __init__(self, private_root: PrivateOutputDirectory, children: dict[str, int]) -> None:
        self._root: PrivateOutputDirectory | None = private_root
        self._children = children

    @classmethod
    def create(cls, destination: str | os.PathLike[str]) -> Self:
        if sys.platform != "linux" or not Path("/proc/self/fd").is_dir():
            raise PrivateOutputError("Linux procfs fd-pinned training paths are unavailable")
        if not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "geteuid")):
            raise PrivateOutputError("Linux private directory descriptor primitives are unavailable")

        root = create_private_directory(destination)
        children: dict[str, int] = {}
        try:
            # create_private_directory pins the fresh mode-0700 root; no
            # absolute pathname lookup is used for these child creations.
            root_fd = root._directory_fd  # owned by shared private-output boundary
            if root_fd is None:
                raise PrivateOutputError("private training root unexpectedly closed")
            for name in ("runtime", "adapter"):
                os.mkdir(name, mode=0o700, dir_fd=root_fd)
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                try:
                    cls._verify_fd(fd)
                except BaseException:
                    os.close(fd)
                    raise
                children[name] = fd
            os.fsync(root_fd)
            broker = cls(root, children)
            broker.verify_live()
            return broker
        except BaseException:
            for fd in children.values():
                os.close(fd)
            root.close()
            # No destructive rollback: incomplete private artifacts are
            # preserved for owner inspection if creation fails partway.
            raise

    @staticmethod
    def _verify_fd(fd: int) -> None:
        attrs = os.fstat(fd)
        if (not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != os.geteuid()
                or stat.S_IMODE(attrs.st_mode) != 0o700):
            raise PrivateOutputError("private training subdirectory owner/mode unverified")
        # Verify the Linux procfd path refers to this exact opened object.
        proc_attrs = os.stat(f"/proc/self/fd/{fd}")
        if (proc_attrs.st_dev, proc_attrs.st_ino) != (attrs.st_dev, attrs.st_ino):
            raise PrivateOutputError("procfd training path does not match pinned directory")

    def _path(self, name: str) -> Path:
        if self._root is None or name not in self._children:
            raise PrivateOutputError("private training broker is closed")
        fd = self._children[name]
        self._verify_fd(fd)
        return Path(f"/proc/self/fd/{fd}")

    @property
    def runtime_path(self) -> Path:
        return self._path("runtime")

    @property
    def adapter_path(self) -> Path:
        return self._path("adapter")

    def write_receipt(self, content: bytes) -> None:
        if self._root is None:
            raise PrivateOutputError("private training broker is closed")
        self._root.write_bytes("training_receipt.json", content)

    def verify_live(self) -> None:
        if self._root is None:
            raise PrivateOutputError("private training broker is closed")
        for fd in self._children.values():
            self._verify_fd(fd)

    def close(self) -> None:
        children, self._children = self._children, {}
        root, self._root = self._root, None
        for fd in children.values():
            os.close(fd)
        if root is not None:
            root.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
