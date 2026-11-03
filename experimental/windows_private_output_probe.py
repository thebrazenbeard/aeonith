"""Non-default Windows private-output *falsification* probes.

Not a writer, not a safe-directory implementation, and not a qualification.
The existing aeonith.private_output Windows rejection remains authoritative.

Only an explicit CLI switch exercises synthetic files and junctions inside a
fresh TemporaryDirectory. No service, real report, ACL, token, or user directory
is changed. Running successfully does not make Windows outputs private.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable


QUALIFICATION_STATUS = "NOT_QUALIFIED"
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_READ_CONTROL = 0x00020000
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_DACL_PROTECTED = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", _FileTime),
        ("accessed", _FileTime),
        ("modified", _FileTime),
        ("volume_serial", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


def classify_security_observation(observation: dict[str, object]) -> dict[str, object]:
    """Flag counterexamples without ever promoting an observation to safety.

    Missing values are UNKNOWN, not PASS. Even a matching owner, non-null DACL,
    and protected inheritance do not prove ACE sufficiency or ancestor custody.
    """
    violations = []
    if observation.get("owner_matches_token_user") is False:
        violations.append("noncaller_owner")
    if observation.get("owner_present") is False:
        violations.append("absent_owner")
    if observation.get("dacl_present") is False:
        violations.append("absent_dacl")
    if observation.get("dacl_is_null") is True:
        violations.append("null_dacl")
    if observation.get("dacl_protected") is False:
        violations.append("inherited_dacl")
    if observation.get("ancestor_redirect_observed") is True:
        violations.append("ancestor_reparse_traversed")
    if observation.get("reparse_point_present") is True:
        violations.append("reparse_point_present")
    return {
        "qualification_status": QUALIFICATION_STATUS,
        "falsifiers": violations,
        "unknowns_remain": True,
    }


class _Handle:
    def __init__(self, value: int, close: Callable[[int], object]):
        self.value = value
        self._close = close

    def __enter__(self) -> int:
        return self.value

    def __exit__(self, *_args: object) -> None:
        self._close(self.value)


def _win32():
    # Bind only when the explicitly opted-in probe runs on Windows.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetFileAttributesW.restype = wintypes.DWORD
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    return kernel32, advapi32


def _open_existing(kernel32, path: Path, *, directory: bool = False) -> _Handle:
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    handle = kernel32.CreateFileW(
        str(path), _READ_CONTROL | _FILE_READ_ATTRIBUTES, _FILE_SHARE_ALL,
        None, _OPEN_EXISTING, flags, None,
    )
    # HANDLE is pointer-sized; INVALID_HANDLE_VALUE is all-bits-one.
    value = ctypes.c_void_p(handle).value
    if value is None or value == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    return _Handle(value, kernel32.CloseHandle)


def _final_path(kernel32, handle: int) -> str:
    chars = 32768
    buffer = ctypes.create_unicode_buffer(chars)
    count = kernel32.GetFinalPathNameByHandleW(handle, buffer, chars, 0)
    if not count or count >= chars:
        raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    return buffer.value


def _file_identity(kernel32, handle: int) -> tuple[int, int, int]:
    info = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle failed")
    return (info.volume_serial, info.index_high, info.index_low)


def _token_user_sid(kernel32, advapi32) -> tuple[_Handle, object, int]:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    token_value = ctypes.c_void_p(token.value).value
    if token_value is None:
        raise RuntimeError("token handle unavailable")
    token_owner = _Handle(token_value, kernel32.CloseHandle)
    try:
        needed = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token.value, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if not needed.value or needed.value > 65536:
            raise RuntimeError("token user buffer size unavailable")
        data = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token.value, _TOKEN_USER, data, needed.value, ctypes.byref(needed)
        ):
            raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        if not sid:
            raise RuntimeError("token user SID missing")
        return token_owner, data, sid
    except BaseException:
        token_owner.__exit__()
        raise


def _security_observation(kernel32, advapi32, path: Path) -> dict[str, object]:
    with _open_existing(kernel32, path, directory=True) as handle:
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        result = advapi32.GetSecurityInfo(
            handle, _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner), None, ctypes.byref(dacl), None,
            ctypes.byref(descriptor),
        )
        if result:
            raise OSError(result, "GetSecurityInfo failed")
        try:
            control = wintypes.WORD(0)
            revision = wintypes.DWORD(0)
            if not advapi32.GetSecurityDescriptorControl(
                descriptor, ctypes.byref(control), ctypes.byref(revision)
            ):
                raise OSError(ctypes.get_last_error(), "GetSecurityDescriptorControl failed")
            with_token, token_data, user_sid = _token_user_sid(kernel32, advapi32)
            try:
                owner_match = bool(owner.value and advapi32.EqualSid(owner, user_sid))
            finally:
                with_token.__exit__()
                del token_data  # Preserve token SID buffer until after EqualSid.
            return {
                "owner_present": bool(owner.value),
                "owner_matches_token_user": owner_match,
                "dacl_present": bool(control.value & 0x0004),
                "dacl_is_null": not bool(dacl.value),
                "dacl_protected": bool(control.value & _SE_DACL_PROTECTED),
                # Real ACE evaluation / effective access remains unproven.
                "ace_rights_qualified": False,
            }
        finally:
            kernel32.LocalFree(descriptor)


def _safe_junction_paths(link: Path, target: Path, root: Path) -> bool:
    """Keep cmd.exe metacharacters out of the synthetic junction command."""
    paths = [link.resolve(strict=False), target.resolve(strict=False)]
    real_root = root.resolve()
    return all(
        p != real_root and real_root in p.parents
        and re.fullmatch(r"[A-Za-z0-9 _:\\\\./-]+", str(p)) is not None
        for p in paths
    )


def _trusted_cmd_path(kernel32) -> Path:
    """Resolve a system binary without PATH, CWD, or COMSPEC lookup."""
    kernel32.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel32.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    count = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not count or count >= len(buffer):
        raise RuntimeError("trusted Windows system directory unavailable")
    path = Path(buffer.value) / "cmd.exe"
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError("trusted Windows command interpreter unavailable")
    return path


def _make_junction(link: Path, target: Path, root: Path, kernel32) -> None:
    if link.exists() or link.is_symlink() or not _safe_junction_paths(link, target, root):
        raise ValueError("unsafe or occupied synthetic junction path")
    command = [
        str(_trusted_cmd_path(kernel32)), "/d", "/c",
        "mklink", "/J", str(link), str(target),
    ]
    try:
        result = subprocess.run(
            # `/d` suppresses cmd AutoRun. `cwd` is also disposable, never
            # the caller's checkout; no executable search in PATH or CWD.
            command, cwd=str(root), check=False,
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        # TimeoutExpired contains the command and file paths. Do not allow it
        # to escape the sanitized JSON reporting boundary.
        raise RuntimeError("synthetic junction command timed out") from None
    except OSError:
        raise RuntimeError("synthetic junction command unavailable") from None
    if result.returncode != 0:
        raise RuntimeError("temporary junction creation unavailable")


def _probe_reparse(kind: str, root: Path, kernel32, advapi32) -> dict[str, object]:
    # root is a new TemporaryDirectory. Every file here is a synthetic marker.
    trial = root / kind
    trial.mkdir()
    parent = trial / "parent"
    parent.mkdir()
    moved = trial / "parent-moved"
    target = trial / "target"
    target.mkdir()
    sentinel = "probe-marker.txt"
    (parent / sentinel).write_text("ORIGINAL", encoding="ascii")
    (target / sentinel).write_text("TARGET", encoding="ascii")

    before = _security_observation(kernel32, advapi32, parent)
    # Deterministic check-to-open swap: the observed parent is no longer at
    # its checked name. The attacker-controlled junction occupies that name.
    parent.rename(moved)
    if kind == "junction":
        _make_junction(parent, target, root, kernel32)
    elif kind == "symlink":
        os.symlink(target, parent, target_is_directory=True)
    else:
        raise ValueError("unknown synthetic reparse kind")

    attrs = kernel32.GetFileAttributesW(str(parent))
    if attrs == _INVALID_FILE_ATTRIBUTES:
        raise OSError(ctypes.get_last_error(), "GetFileAttributesW failed")
    with _open_existing(kernel32, parent / sentinel) as handle:
        final_name = _final_path(kernel32, handle)
        via_id = _file_identity(kernel32, handle)
    with _open_existing(kernel32, target / sentinel) as direct_handle:
        target_id = _file_identity(kernel32, direct_handle)
    # No paths leave the probe in the JSON receipt.
    normalized = lambda s: ntpath.normcase(ntpath.normpath(str(s).removeprefix("\\\\?\\")))
    path_match = normalized(final_name) == normalized(target / sentinel)
    # Microsoft documents volume + file index comparison as evidence that
    # two open handles resolve to the same object, regardless of DOS aliases.
    identity_match = via_id == target_id
    redirected = path_match or identity_match
    observed = {
        **before,
        "reparse_point_present": bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT),
        "ancestor_redirect_observed": redirected,
    }
    return {
        "test": kind,
        "execution": "EXECUTED",
        "parent_renamed_before_open": True,
        "opened_target_identity_after_swap": identity_match,
        "opened_target_normalized_path_after_swap": path_match,
        "observations": observed,
        "verdict": classify_security_observation(observed),
    }


def run_disposable_windows_probes() -> dict[str, object]:
    """Never call from production; performs only isolated synthetic temp I/O."""
    if os.name != "nt":
        return {"qualification_status": QUALIFICATION_STATUS, "execution": "NOT_RUN_NON_WINDOWS"}
    kernel32, advapi32 = _win32()
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="aeonith-win-priv-probe-") as raw_root:
        root = Path(raw_root)
        for kind in ("junction", "symlink"):
            try:
                cases.append(_probe_reparse(kind, root, kernel32, advapi32))
            except (OSError, RuntimeError, ValueError) as exc:
                # No path / token / private content in the result.
                cases.append({
                    "test": kind,
                    "execution": "INCONCLUSIVE",
                    "error_class": type(exc).__name__,
                })
    return {
        "qualification_status": QUALIFICATION_STATUS,
        "scope": "synthetic-disposable-temp-only",
        "real_private_output_qualified": False,
        "cases": cases,
        "warning": "This harness only searches for counterexamples; it is never an authorization.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-disposable-temp-probes", action="store_true",
        help="Explicitly opt in to synthetic temp-only Windows ACL/reparse/rename probes",
    )
    args = parser.parse_args(argv)
    receipt = (
        run_disposable_windows_probes()
        if args.run_disposable_temp_probes
        else {"qualification_status": QUALIFICATION_STATUS, "execution": "NOT_RUN_OPT_IN_REQUIRED"}
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0  # This is probe execution status, NOT security qualification.


if __name__ == "__main__":
    raise SystemExit(main())
