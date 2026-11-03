"""Read-only Windows memory preflight; never starts WSL, loads a model or trains.

This is an *observation*, not permission to run the CPU model-load experiment.
The existing experiment requires a fresh Windows reserve check **after WSL is
running** and an independent Linux ``MemAvailable`` measurement. Neither is
established by this Windows-only program.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import ctypes
import io
import json
import ntpath
import os
import re
import subprocess


class MemoryGateError(RuntimeError):
    """Host memory or process inventory could not be observed safely."""


# Prior Aeonith host experiment requires at least 7 GiB free physical Windows
# memory after WSL starts, plus >=6656 MiB within the already-running Linux.
WINDOWS_FREE_FLOOR_MIB = 7 * 1024
WSL_MEMAVAILABLE_FLOOR_MIB = 6656

_WSL_PROCESS_HINTS = frozenset({
    "wsl.exe", "wslhost.exe", "vmmem", "vmmem.exe", "vmmemwsl", "vmmemwsl.exe",
})
_WORKLOAD_PROCESS_NAMES = frozenset({
    "ollama", "ollama.exe", "llama-server", "llama-server.exe",
    "koboldcpp", "koboldcpp.exe", "python.exe", "pythonw.exe",
})


def assess(available_mib: int | None, processes: list[str] | None) -> dict[str, object]:
    """Judge bounded *observation*, never infer an authorized model-load GO."""
    if (available_mib is not None and
            (type(available_mib) is not int or available_mib < 0)):
        raise MemoryGateError("invalid available physical memory reading")
    if processes is not None and (not isinstance(processes, list) or any(
            not isinstance(name, str) for name in processes)):
        raise MemoryGateError("invalid process inventory")
    normalized = None if processes is None else [name.casefold() for name in processes]
    wsl_hint = bool(normalized is not None and _WSL_PROCESS_HINTS.intersection(normalized))
    workloads = ({} if normalized is None else dict(sorted(
        (name, count) for name, count in Counter(normalized).items()
        if name in _WORKLOAD_PROCESS_NAMES
    )))
    return {
        "schema_version": "aeonith.windows_native_memory_preflight.v1",
        "status": "HOLD_NOT_QUALIFIED",
        "windows_available_physical_mib": available_mib,
        "host_memory_floor_mib": WINDOWS_FREE_FLOOR_MIB,
        "host_memory_floor_met": (
            None if available_mib is None else available_mib >= WINDOWS_FREE_FLOOR_MIB),
        "wsl_state": "process_hint_only" if wsl_hint else "unproven",
        "wsl_memavailable_floor_mib": WSL_MEMAVAILABLE_FLOOR_MIB,
        "wsl_memavailable_mib": None,
        "wsl_load_qualified": False,
        "windows_native_model_load_qualified": False,
        "observed_workloads": workloads,
        "process_inventory_available": normalized is not None,
        "model_load_qualified": False,
        "model_loaded": False,
        "forward_passes": 0,
        "optimizer_steps": 0,
        "training_authorized": False,
        "limitations": (
            "No WSL command or model is started; tasklist process hints do not prove a distro "
            "running; WSL MemAvailable and Windows post-WSL reserve are not jointly measured; "
            "native Windows package/output custody and host-owned lease are unqualified."
        ),
    }


def parse_tasklist_csv(source: str) -> list[str]:
    """Use only process image names; malformed/localized failure text is unknown.

    Windows tasklist legitimately lists ``System Idle Process`` as PID 0.
    Ignore that single sentinel while retaining strict positive-PID checks on
    every other row, so a process-inventory failure never looks like success.
    """
    try:
        rows = list(csv.reader(io.StringIO(source.lstrip("\ufeff"))))
        if not rows:
            raise ValueError("malformed task list")
        names: list[str] = []
        idle_seen = False
        for row in rows:
            if len(row) < 2 or not row[0].strip():
                raise ValueError("malformed task list")
            name = row[0].strip().casefold()
            pid = int(row[1].strip())
            if name == "system idle process" and pid == 0 and not idle_seen:
                idle_seen = True
                continue
            if pid <= 0:
                raise ValueError("malformed task list")
            names.append(name)
        return names
    except (csv.Error, ValueError, TypeError) as exc:
        raise MemoryGateError("Windows process inventory unavailable") from exc


def _system_tasklist_executable() -> str:
    """Resolve the protected Windows system directory through the OS API.

    A bare ``tasklist.exe`` would be searched in CWD/PATH and could run an
    attacker-controlled executable. No environment-derived folder is trusted.
    Refuse noncanonical paths even if a native directory API malfunctions.
    """
    def native_directory(api_name: str) -> str:
        directory = ctypes.create_unicode_buffer(32768)
        try:
            api = getattr(ctypes.windll.kernel32, api_name)
            written = api(directory, len(directory))
        except (AttributeError, OSError) as exc:
            raise MemoryGateError("trusted Windows system directory unavailable") from exc
        value = directory.value
        drive, tail = ntpath.splitdrive(value)
        if (not isinstance(written, int) or written <= 0 or written >= len(directory)
                or len(value) != written or not re.fullmatch(r"[A-Za-z]:", drive)
                or not tail.startswith("\\") or "/" in value
                or ntpath.normpath(value) != value):
            raise MemoryGateError("trusted Windows system directory unavailable")
        return value

    windows_root = native_directory("GetWindowsDirectoryW")
    system_dir = native_directory("GetSystemDirectoryW")
    if ntpath.normcase(system_dir) != ntpath.normcase(ntpath.join(windows_root, "System32")):
        raise MemoryGateError("trusted Windows system directory unavailable")
    return ntpath.join(system_dir, "tasklist.exe")


def list_windows_processes() -> list[str]:
    """One absolute-system-binary read-only query, never PATH/CWD search."""
    binary = _system_tasklist_executable()
    try:
        result = subprocess.run(
            [binary, "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=5,
            check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MemoryGateError("Windows process inventory unavailable") from exc
    if result.returncode != 0:
        raise MemoryGateError("Windows process inventory unavailable")
    return parse_tasklist_csv(result.stdout)


def read_windows_available_mib() -> int:
    """Use GlobalMemoryStatusEx without allocating memory or launching tools."""
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in (
                "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual",
            )
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError) as exc:
        raise MemoryGateError("Windows physical memory unavailable") from exc
    if not success or status.ullTotalPhys <= 0:
        raise MemoryGateError("Windows physical memory unavailable")
    return int(status.ullAvailPhys // (1024 * 1024))


def collect(*, platform_name: str | None = None) -> dict[str, object]:
    if (os.name if platform_name is None else platform_name) != "nt":
        return {**assess(None, None), "status": "UNSUPPORTED_PLATFORM"}
    memory: int | None = None
    processes: list[str] | None = None
    try:
        memory = read_windows_available_mib()
    except MemoryGateError:
        pass
    try:
        processes = list_windows_processes()
    except MemoryGateError:
        pass
    return assess(memory, processes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Windows memory preflight; NEVER trains")
    parser.add_argument("--inspect", action="store_true", help="read Windows memory and processes")
    args = parser.parse_args(argv)
    if not args.inspect:
        print(json.dumps({"status": "NOT_EXECUTED", "model_loaded": False,
                          "optimizer_steps": 0}, sort_keys=True))
        return 2
    report = collect()
    print(json.dumps(report, sort_keys=True))
    return 2  # A preflight observation cannot qualify a model load or trainer.


if __name__ == "__main__":
    raise SystemExit(main())
