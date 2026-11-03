"""Prototype Linux output custody for future local optimizer qualification.

This is **not** wired into train_lora. Trainer/PEFT path canonicalization,
subprocess behavior and genuine optimizer writes are still unqualified.
The training launch gate must remain closed until those integrations are tested.

For same-process, literal pathname operations on Linux, /proc/self/fd/N
identifies an opened directory object, not the user's mutable spelling of its
ancestors. The descriptors remain open for the whole broker context.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import stat
import sys
from typing import Self

from aeonith.private_output import (
    PrivateOutputDirectory, PrivateOutputError, create_private_directory,
)


@dataclass(frozen=True)
class _ChildDirectoryIdentity:
    """One inherited descriptor and the observed filesystem object identity."""

    fd: int
    device: int
    inode: int
    uid: int

    @classmethod
    def from_fd(cls, fd: int) -> Self:
        PinnedTrainingArtifacts._verify_fd(fd)
        attrs = os.fstat(fd)
        return cls(fd, attrs.st_dev, attrs.st_ino, attrs.st_uid)

    def verify(self) -> None:
        if sys.platform != "linux" or not Path("/proc/self/fd").is_dir():
            raise PrivateOutputError("child output descriptor verification requires Linux procfs")
        try:
            PinnedTrainingArtifacts._verify_fd(self.fd)
            attrs = os.fstat(self.fd)
        except (OSError, ValueError) as exc:
            raise PrivateOutputError("child output descriptor is missing or invalid") from exc
        if (attrs.st_dev, attrs.st_ino, attrs.st_uid) != (self.device, self.inode, self.uid):
            raise PrivateOutputError("child output descriptor identity changed")


@dataclass(frozen=True)
class TrainingChildHandoff:
    """Explicit, *untrusted-until-verified* Linux descriptor handoff record.

    The parent must hold the broker open while spawning a *trusted* child with
    subprocess pass_fds=handoff.pass_fds. The child parses the exact record and
    calls verify_current_process() before using fd-relative operations. This
    record has no authentication or revocation; it does not qualify external
    ML frameworks or authorize arbitrary child executables.
    """

    runtime: _ChildDirectoryIdentity
    adapter: _ChildDirectoryIdentity

    @property
    def pass_fds(self) -> tuple[int, int]:
        return tuple(sorted((self.runtime.fd, self.adapter.fd)))

    def to_json(self) -> str:
        return json.dumps({
            "schema": 1,
            "runtime": vars(self.runtime),
            "adapter": vars(self.adapter),
        }, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, data: str) -> Self:
        """Parse a bounded, exact-shape transport record; not an authorization."""
        if not isinstance(data, str) or len(data) > 2048:
            raise PrivateOutputError("invalid child output handoff transport")

        def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise PrivateOutputError("duplicate child output handoff field")
                result[key] = value
            return result

        try:
            payload = json.loads(data, object_pairs_hook=no_duplicate_keys)
        except (ValueError, TypeError) as exc:
            raise PrivateOutputError("invalid child output handoff JSON") from exc
        if (not isinstance(payload, dict)
                or set(payload) != {"schema", "runtime", "adapter"}
                or type(payload["schema"]) is not int
                or payload["schema"] != 1):
            raise PrivateOutputError("unexpected child output handoff schema")
        parsed = {}
        for name in ("runtime", "adapter"):
            item = payload[name]
            if not isinstance(item, dict) or set(item) != {"fd", "device", "inode", "uid"}:
                raise PrivateOutputError("unexpected child output descriptor schema")
            if any(type(value) is not int or value < 0 for value in item.values()) or item["fd"] < 3:
                raise PrivateOutputError("invalid child output descriptor identity")
            parsed[name] = _ChildDirectoryIdentity(**item)
        if parsed["runtime"].fd == parsed["adapter"].fd:
            raise PrivateOutputError("runtime and adapter output descriptors must differ")
        return cls(**parsed)

    def verify_current_process(self) -> dict[str, int]:
        """Return inherited fds *only after* checking both exact identities.

        Use os.open(name, flags, mode, dir_fd=fd), not Path.resolve() or
        absolute paths. Verification is time-of-check only: the caller must
        avoid closing/reassigning these descriptors throughout subsequent work.
        """
        if self.runtime.fd == self.adapter.fd:
            raise PrivateOutputError("runtime and adapter output descriptors must differ")
        self.runtime.verify()
        self.adapter.verify()
        return {"runtime": self.runtime.fd, "adapter": self.adapter.fd}


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

    def write_adapter_bytes(self, filename: str, content: bytes) -> None:
        """Create one exclusive PEFT-named artifact through the pinned child fd.

        This only qualifies *opaque, already-serialized bytes* written by our
        own code. It does not validate a safetensors payload, admit a model,
        qualify an ML trainer's path-based outputs, or enable training.
        File creation is exclusive; an interrupted two-file bundle is never
        claimed to be an atomic checkpoint or silently removed.
        """
        if filename not in {"adapter_config.json", "adapter_model.safetensors"}:
            raise PrivateOutputError("private adapter artifact name is not allowlisted")
        if self._root is None or "adapter" not in self._children:
            raise PrivateOutputError("private training broker is closed")
        self.verify_live()
        # Duplication gives this write a temporary owned fd. The original
        # broker retains custody even if the private writer closes its copy.
        writer_fd = os.dup(self._children["adapter"])
        with PrivateOutputDirectory(Path("/proc/self/fd") / str(writer_fd), writer_fd) as writer:
            self._verify_fd(writer_fd)
            try:
                writer.write_bytes(filename, content)
            except FileExistsError as exc:
                raise PrivateOutputError("private adapter artifact already exists") from exc
            except OSError as exc:
                raise PrivateOutputError("private adapter artifact write failed") from exc

    def verify_live(self) -> None:
        if self._root is None:
            raise PrivateOutputError("private training broker is closed")
        for fd in self._children.values():
            self._verify_fd(fd)

    def child_handoff(self) -> TrainingChildHandoff:
        """Describe currently pinned fds for explicit trusted-child inheritance."""
        self.verify_live()
        return TrainingChildHandoff(
            _ChildDirectoryIdentity.from_fd(self._children["runtime"]),
            _ChildDirectoryIdentity.from_fd(self._children["adapter"]),
        )

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
