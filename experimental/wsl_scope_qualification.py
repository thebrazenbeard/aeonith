"""Opt-in, disposable WSL2 user-scope resource-limit qualification.

This does not import ML packages, load weights, stress resources or train.
It establishes only what the *current* tiny scoped process can read back.
It is not a lease for any later, different process.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any


class ScopeQualificationError(RuntimeError):
    """The disposable scope or its effective resource limits were not proven."""


_CGROUP_ROOT = Path("/sys/fs/cgroup")
_CGROUP_MEM = 512 * 1024 * 1024
_CGROUP_HIGH = 384 * 1024 * 1024
_CPU_QUOTA = (1, 4)
_PIDS = 16
_TIMEOUT_SECONDS = 20


def _controllers_available() -> None:
    if not sys.platform.startswith("linux") or not hasattr(os, "geteuid") or os.geteuid() == 0:
        raise ScopeQualificationError("requires an ordinary Linux user")
    try:
        init = Path("/proc/1/comm").read_text(encoding="ascii").strip()
        controllers = set((_CGROUP_ROOT / "cgroup.controllers").read_text(encoding="ascii").split())
    except OSError as exc:
        raise ScopeQualificationError("cgroup v2 preflight unavailable") from exc
    if init != "systemd" or not {"cpu", "memory", "pids"}.issubset(controllers):
        raise ScopeQualificationError("systemd/cgroup v2 controllers unavailable")


def _read_child_cgroup(unit: str, *, root: Path = _CGROUP_ROOT,
                       membership: Path = Path("/proc/self/cgroup")) -> dict[str, Any]:
    """Read *effective* cgroup control files from inside the scoped child."""
    if not unit.startswith("aeonith-scopecheck-") or not unit.endswith(".scope") or "/" in unit:
        raise ScopeQualificationError("invalid disposable unit name")
    try:
        entries = [line.split(":", 2) for line in membership.read_text(encoding="ascii").splitlines()]
        if len(entries) != 1 or len(entries[0]) != 3 or entries[0][:2] != ["0", ""]:
            raise ScopeQualificationError("not a unified cgroup v2 process")
        relative = Path(entries[0][2])
        if not relative.is_absolute() or unit not in relative.parts or ".." in relative.parts:
            raise ScopeQualificationError("process is not in its requested unit")
        cgroup = root.joinpath(*relative.parts[1:])
        observed = {
            "memory_max": (cgroup / "memory.max").read_text(encoding="ascii").strip(),
            "memory_high": (cgroup / "memory.high").read_text(encoding="ascii").strip(),
            "memory_swap_max": (cgroup / "memory.swap.max").read_text(encoding="ascii").strip(),
            "cpu_max": (cgroup / "cpu.max").read_text(encoding="ascii").strip(),
            "pids_max": (cgroup / "pids.max").read_text(encoding="ascii").strip(),
        }
    except ScopeQualificationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ScopeQualificationError("effective cgroup files could not be read") from exc
    if observed["memory_max"] != str(_CGROUP_MEM) or observed["memory_high"] != str(_CGROUP_HIGH):
        raise ScopeQualificationError("effective memory limits mismatch requested values")
    if observed["memory_swap_max"] != "0" or observed["pids_max"] != str(_PIDS):
        raise ScopeQualificationError("effective swap/task limits mismatch requested values")
    try:
        quota, period = map(int, observed["cpu_max"].split())
        if quota <= 0 or period <= 0 or quota * _CPU_QUOTA[1] != period * _CPU_QUOTA[0]:
            raise ScopeQualificationError("effective CPU quota mismatch requested value")
    except (ValueError, TypeError):
        raise ScopeQualificationError("effective CPU quota is malformed") from None
    return {
        "schema_version": "aeonith.scope_limits_probe.v1",
        "status": "process_effective_limits_verified",
        "unit": unit,
        "effective": observed,
        "requested_memory_max_bytes": _CGROUP_MEM,
        "requested_memory_high_bytes": _CGROUP_HIGH,
        "requested_cpu_ratio": "1/4",
        "requested_pids_max": _PIDS,
        "requested_swap_max_bytes": 0,
        "model_loaded": False,
        "optimizer_steps": 0,
        "training_lease_established": False,
    }


def _show_unit(unit: str) -> dict[str, str]:
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "show", unit,
             "--property=LoadState,ActiveState,ControlGroup"],
            text=True, capture_output=True, check=False, timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScopeQualificationError("temporary unit state unavailable") from exc
    if completed.returncode != 0:
        raise ScopeQualificationError("cannot inspect disposable scope")
    properties: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            properties[key] = value
    if set(properties) != {"LoadState", "ActiveState", "ControlGroup"}:
        raise ScopeQualificationError("disposable unit state is malformed")
    return properties


def _stop_owned_unit(unit: str) -> None:
    try:
        subprocess.run(["systemctl", "--user", "stop", unit],
                       check=False, capture_output=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _assert_unloaded(unit: str) -> None:
    for attempt in range(4):
        properties = _show_unit(unit)
        if (properties["LoadState"] == "not-found"
                and properties["ActiveState"] == "inactive"
                and properties["ControlGroup"] == ""):
            return
        if attempt < 3:
            time.sleep(0.25)
    raise ScopeQualificationError("disposable scope has not disappeared")


def run_qualification() -> dict[str, Any]:
    """Launch at most one tiny scope; read child receipt and ensure teardown."""
    _controllers_available()
    unit = f"aeonith-scopecheck-{os.getpid()}-{secrets.token_hex(12)}.scope"
    # Never ask systemd to use or stop a pre-existing unit, even by accident.
    _assert_unloaded(unit)
    command = [
        "systemd-run", "--user", "--scope", f"--unit={unit}",
        "--property=MemoryMax=512M", "--property=MemoryHigh=384M",
        "--property=MemorySwapMax=0", "--property=CPUQuota=25%",
        "--property=TasksMax=16",
        sys.executable, str(Path(__file__).resolve()), "--child", "--unit", unit,
    ]
    failure = None
    try:
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       check=False, timeout=_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScopeQualificationError("disposable systemd scope failed or timed out") from exc
        if completed.returncode != 0:
            raise ScopeQualificationError("disposable scoped child exited nonzero")
        matching = []
        for line in completed.stdout.splitlines():
            if not line.startswith("{") or len(line) > 4096:
                continue
            try:
                item = json.loads(line)
            except (ValueError, TypeError):
                raise ScopeQualificationError("scoped child emitted malformed receipt") from None
            if isinstance(item, dict) and item.get("schema_version") == "aeonith.scope_limits_probe.v1":
                matching.append(item)
        if len(matching) != 1:
            raise ScopeQualificationError("no unique child cgroup receipt")
        receipt = matching[0]
        if receipt.get("unit") != unit or receipt.get("status") != "process_effective_limits_verified":
            raise ScopeQualificationError("scoped child receipt does not match unit")
    except ScopeQualificationError as exc:
        failure = exc
        receipt = None
    finally:
        # Stop only the preflight-absent, random unit attempted here, never shared services.
        _stop_owned_unit(unit)
        _assert_unloaded(unit)
    if failure is not None:
        raise failure
    assert receipt is not None
    receipt["temporary_scope_unloaded"] = True
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disposable WSL user cgroup verification; no training")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--unit", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        if args.execute or not args.unit:
            return 2
        try:
            result = _read_child_cgroup(args.unit)
        except ScopeQualificationError:
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0
    if not args.execute or args.unit:
        print(json.dumps({"status": "not_executed", "training_lease_established": False}))
        return 2
    try:
        result = run_qualification()
    except ScopeQualificationError:
        print("Disposable WSL scope could not prove effective limits", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
