"""Opt-in synthetic test of Windows NT file creation *relative to a pinned handle*.

NOT a production writer or a private ACL guarantee. The caller opens a
disposable directory handle, renames that directory, and replaces its former
name with an ancestor junction/symlink. NtCreateFile uses RootDirectory to
create a test marker. It must land in the renamed directory, not the decoy.
No real manuscripts, services, models, credentials, or ACLs are involved.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile

from . import windows_private_output_probe as prior


STATUS = "NOT_QUALIFIED"
_FILE_TRAVERSE = 0x00000020
_FILE_READ_ATTRIBUTES = 0x00000080
_READ_CONTROL = 0x00020000
_SYNCHRONIZE = 0x00100000
_GENERIC_WRITE = 0x40000000
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_CREATE = 2
_OBJ_CASE_INSENSITIVE = 0x00000040


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", wintypes.LPWSTR),
    ]


class _IoStatusUnion(ctypes.Union):
    _fields_ = [("Status", wintypes.LONG), ("Pointer", ctypes.c_void_p)]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [("Result", _IoStatusUnion), ("Information", ctypes.c_void_p)]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


def _marker_basename(name: str) -> str:
    """Use only a fixed ASCII basename, never NT device or path syntax."""
    if type(name) is not str or name != "relative-pinned-marker.bin":
        raise ValueError("a fixed disposable marker basename is required")
    return name


def _nt_create_relative_file(root_handle: int, name: str, kernel32, ntdll) -> prior._Handle:
    """Create once inside an already-open directory, without a pathname fallback.

    This verifies only a name-resolution property. It makes NO claims about
    the initial root handle's ancestry or the effective DACL of the child.
    """
    _marker_basename(name)
    if type(root_handle) is not int or root_handle <= 0:
        raise ValueError("a valid pre-opened directory handle is required")
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes), ctypes.POINTER(_IoStatusBlock),
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    ntdll.NtCreateFile.restype = wintypes.LONG
    name_buffer = ctypes.create_unicode_buffer(name)
    encoded = name.encode("utf-16-le")
    unicode_name = _UnicodeString(
        len(encoded), len(encoded) + 2,
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _ObjectAttributes(
        ctypes.sizeof(_ObjectAttributes), wintypes.HANDLE(root_handle),
        ctypes.pointer(unicode_name), _OBJ_CASE_INSENSITIVE, None, None,
    )
    iosb = _IoStatusBlock()
    created = wintypes.HANDLE()
    status = ntdll.NtCreateFile(
        ctypes.byref(created),
        _GENERIC_WRITE | _FILE_READ_ATTRIBUTES | _READ_CONTROL | _SYNCHRONIZE,
        ctypes.byref(attributes), ctypes.byref(iosb), None,
        _FILE_ATTRIBUTE_NORMAL, 0, _FILE_CREATE,
        _FILE_NON_DIRECTORY_FILE | _FILE_OPEN_REPARSE_POINT | _FILE_SYNCHRONOUS_IO_NONALERT,
        None, 0,
    )
    if status < 0:
        raise RuntimeError("root-relative NtCreateFile unavailable")
    if not created.value or created.value == ctypes.c_void_p(-1).value:
        raise RuntimeError("root-relative NtCreateFile returned invalid handle")
    return prior._Handle(int(created.value), kernel32.CloseHandle)


def _open_root_for_child(kernel32, parent: Path) -> prior._Handle:
    """Pin a directory for relative opens; no qualified ancestor policy yet."""
    handle = kernel32.CreateFileW(
        str(parent),
        _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _READ_CONTROL | _SYNCHRONIZE,
        prior._FILE_SHARE_ALL, None, prior._OPEN_EXISTING,
        prior._FILE_FLAG_BACKUP_SEMANTICS | prior._FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    value = ctypes.c_void_p(handle).value
    if value is None or value == ctypes.c_void_p(-1).value:
        raise RuntimeError("synthetic directory handle unavailable")
    return prior._Handle(value, kernel32.CloseHandle)


def _probe_one(kind: str, root: Path, kernel32, advapi32, ntdll) -> dict[str, object]:
    trial = root / kind
    trial.mkdir()
    parent = trial / "parent"
    moved = trial / "moved"
    decoy = trial / "decoy"
    parent.mkdir()
    decoy.mkdir()
    marker = "relative-pinned-marker.bin"
    # This absolute initial open is deliberately not an ACL/provenance proof.
    with _open_root_for_child(kernel32, parent) as original_handle:
        pinned_identity = prior._file_identity(kernel32, original_handle)
        parent.rename(moved)
        if kind == "junction":
            prior._make_junction(parent, decoy, root, kernel32)
        elif kind == "symlink":
            os.symlink(decoy, parent, target_is_directory=True)
        else:
            raise ValueError("unsupported synthetic test case")
        # The same-SID test actor changes a path after the handle was opened.
        # The verified result is the identity of the created *test* file only.
        with _nt_create_relative_file(original_handle, marker, kernel32, ntdll) as created_handle:
            created_identity = prior._file_identity(kernel32, created_handle)
        with prior._open_existing(kernel32, moved / marker) as by_moved:
            rooted_match = created_identity == prior._file_identity(kernel32, by_moved)
        with prior._open_existing(kernel32, moved, directory=True) as moved_handle:
            identity_preserved = prior._file_identity(kernel32, moved_handle) == pinned_identity
    return {
        "test": kind,
        "execution": "EXECUTED",
        "same_sid_ancestor_swap": True,
        "original_directory_handle_identity_preserved": identity_preserved,
        "rooted_create_landed_in_pinned_directory": rooted_match,
        "decoy_marker_created": (decoy / marker).exists(),
        "qualification_status": STATUS,
        "private_acl_qualified": False,
    }


def run_disposable_rootdir_probes() -> dict[str, object]:
    """Falsification on disposable files only; never changes production gates."""
    if os.name != "nt":
        return {"qualification_status": STATUS, "execution": "NOT_RUN_NON_WINDOWS"}
    kernel32, advapi32 = prior._win32()
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="aeonith-win-rootdir-probe-") as raw:
        root = Path(raw)
        for kind in ("junction", "symlink"):
            try:
                results.append(_probe_one(kind, root, kernel32, advapi32, ntdll))
            except (OSError, RuntimeError, ValueError):
                results.append({
                    "test": kind, "execution": "INCONCLUSIVE",
                    "error_class": "synthetic_handle_probe_failed",
                })
    return {
        "qualification_status": STATUS,
        "scope": "synthetic-disposable-temp-only",
        "real_private_output_qualified": False,
        "same_sid_acl_isolation_qualified": False,
        "cases": results,
        "warning": "A pinned handle is not an effective-DACL or production writer proof.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-disposable-temp-probes", action="store_true")
    args = parser.parse_args(argv)
    receipt = (run_disposable_rootdir_probes() if args.run_disposable_temp_probes
               else {"qualification_status": STATUS, "execution": "NOT_RUN_OPT_IN_REQUIRED"})
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
