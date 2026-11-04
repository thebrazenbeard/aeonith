"""One-shot, host-scoped Qwen3.5 CPU model-load qualification; never trains.

This experiment neither admits any corpus nor constructs an optimizer. A tiny
scope test is not a training lease, and even a successful model-load receipt
does not establish protected loader custody or trainability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import subprocess
import sys
from typing import Any

from experimental.wsl_scope_qualification import (
    ScopeQualificationError, _assert_unloaded, _controllers_available,
    _stop_owned_unit,
)


class ModelLoadQualificationError(RuntimeError):
    """A bounded model load or its exact resource/custody checks failed."""


_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"
_BASE_MODEL = "Qwen/Qwen3.5-0.8B"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = (_REPO_ROOT / "training" / "manifests"
             / f"qwen3.5-0.8b-{_REVISION}.json")
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_MEMORY_MAX = 4608 * 1024 * 1024
_MEMORY_HIGH = 4096 * 1024 * 1024
_CPU_RATIO = (1, 2)
_PIDS_MAX = 64
_TIMEOUT = 120


def _private_base(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise ModelLoadQualificationError("checkpoint path is not an absolute local path")
    if any(item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction())
           for item in (path, *path.parents)):
        raise ModelLoadQualificationError("checkpoint path contains an indirect component")
    try:
        attributes = path.stat()
    except OSError as exc:
        raise ModelLoadQualificationError("checkpoint directory cannot be inspected") from exc
    if (not stat.S_ISDIR(attributes.st_mode) or attributes.st_uid != os.geteuid()
            or attributes.st_mode & 0o077):
        raise ModelLoadQualificationError("checkpoint directory must be owner-private")
    return path


def _available_memory_mib() -> int:
    try:
        lines = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
        values = [line for line in lines if line.startswith("MemAvailable:")]
        if len(values) != 1:
            raise ValueError("MemAvailable missing")
        mib = int(values[0].split()[1]) // 1024
    except (OSError, ValueError, IndexError) as exc:
        raise ModelLoadQualificationError("available host RAM cannot be read") from exc
    # Preserve at least 2 GiB of host-visible WSL headroom beyond this job.
    # A separate fresh Windows memory readback is still required by the owner.
    if mib < 6656:
        raise ModelLoadQualificationError("insufficient WSL RAM headroom for bounded load")
    return mib


def _read_own_scope(unit: str, *, root: Path = _CGROUP_ROOT,
                    membership: Path = Path("/proc/self/cgroup")) -> tuple[Path, dict[str, str]]:
    """Reject a child outside the exact random systemd user scope."""
    if (not unit.startswith("aeonith-modelcheck-") or not unit.endswith(".scope")
            or "/" in unit or "\\" in unit):
        raise ModelLoadQualificationError("invalid disposable unit")
    try:
        lines = [line.split(":", 2) for line in membership.read_text(encoding="ascii").splitlines()]
        if len(lines) != 1 or len(lines[0]) != 3 or lines[0][:2] != ["0", ""]:
            raise ModelLoadQualificationError("not a unified cgroup process")
        relative = PurePosixPath(lines[0][2])
        if not relative.is_absolute() or unit not in relative.parts or ".." in relative.parts:
            raise ModelLoadQualificationError("child not in requested scope")
        directory = root.joinpath(*relative.parts[1:])
        keys = {"memory_max": "memory.max", "memory_high": "memory.high",
                "swap_max": "memory.swap.max", "cpu_max": "cpu.max",
                "pids_max": "pids.max"}
        observed = {key: (directory / filename).read_text(encoding="ascii").strip()
                    for key, filename in keys.items()}
    except ModelLoadQualificationError:
        raise
    except (OSError, ValueError, UnicodeError) as exc:
        raise ModelLoadQualificationError("effective scope limits unavailable") from exc
    if observed["memory_max"] != str(_MEMORY_MAX) or observed["memory_high"] != str(_MEMORY_HIGH):
        raise ModelLoadQualificationError("memory caps were not enforced")
    if observed["swap_max"] != "0" or observed["pids_max"] != str(_PIDS_MAX):
        raise ModelLoadQualificationError("swap/tasks caps were not enforced")
    try:
        quota, period = (int(value) for value in observed["cpu_max"].split())
        if quota <= 0 or period <= 0 or quota * _CPU_RATIO[1] != period * _CPU_RATIO[0]:
            raise ModelLoadQualificationError("CPU cap was not enforced")
    except ValueError:
        raise ModelLoadQualificationError("invalid effective CPU cap") from None
    return directory, observed


def _child_model_load(base: str, unit: str) -> dict[str, Any]:
    _controllers_available()
    source = _private_base(base)
    directory, controls = _read_own_scope(unit)
    try:
        from training.train_lora import require_actual_cpu_float32_model
        from training.verify_base import verify_checkpoint
        verified = verify_checkpoint(source, _MANIFEST, expected_model=_BASE_MODEL,
                                     expected_revision=_REVISION)
        os.environ.update({
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
            "HF_DATASETS_OFFLINE": "1", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
        })
        import torch
        from transformers import AutoModelForCausalLM
        model = AutoModelForCausalLM.from_pretrained(
            str(source), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.float32,
        )
        dtype = require_actual_cpu_float32_model(model, torch)
        peak = int((directory / "memory.peak").read_text(encoding="ascii").strip())
        current = int((directory / "memory.current").read_text(encoding="ascii").strip())
        events = (directory / "memory.events").read_text(encoding="ascii").splitlines()
        if peak <= 0 or peak > _MEMORY_MAX or current < 0 or current > _MEMORY_MAX:
            raise ModelLoadQualificationError("memory accounting exceeded scoped cap")
        if any(line.startswith("oom_kill ") and int(line.split()[1]) > 0 for line in events):
            raise ModelLoadQualificationError("cgroup observed OOM kill")
        return {
            "schema_version": "aeonith.qwen_cpu_load_probe.v1",
            "status": "scoped_cpu_float32_model_loaded_not_training_qualified",
            "unit": unit,
            "model_id": _BASE_MODEL,
            "revision_declared": _REVISION,
            "verified_files": verified["files_verified"],
            "manifest_sha256": verified["expected_manifest_sha256"],
            "cpu_float32_parameter_count": dtype["cpu_float32_parameter_count"],
            "effective_controls": controls,
            "cgroup_memory_peak_bytes": peak,
            "cgroup_memory_current_bytes": current,
            "model_loaded": True,
            "forward_passes": 0,
            "optimizer_steps": 0,
            "trained_adapter_created": False,
            "protected_loader_custody": False,
            "training_lease_established": False,
        }
    except ModelLoadQualificationError:
        raise
    except Exception:
        # A failed dependency/loader must not leak local paths or source bytes.
        raise ModelLoadQualificationError("offline model-load or dtype verification failed") from None


def _validate_child_receipt(receipt: Any, unit: str) -> dict[str, Any]:
    """Never promote a truncated or partly spoofed stdout object to PASS."""
    keys = {"schema_version", "status", "unit", "model_id", "revision_declared",
            "verified_files", "manifest_sha256", "cpu_float32_parameter_count",
            "effective_controls", "cgroup_memory_peak_bytes",
            "cgroup_memory_current_bytes", "model_loaded", "forward_passes",
            "optimizer_steps", "trained_adapter_created", "protected_loader_custody",
            "training_lease_established"}
    if not isinstance(receipt, dict) or set(receipt) != keys:
        raise ModelLoadQualificationError("model-load receipt has missing or unexpected fields")
    if (receipt["schema_version"] != "aeonith.qwen_cpu_load_probe.v1"
            or receipt["status"] != "scoped_cpu_float32_model_loaded_not_training_qualified"
            or receipt["unit"] != unit or receipt["model_id"] != _BASE_MODEL
            or receipt["revision_declared"] != _REVISION
            or receipt["model_loaded"] is not True
            or receipt["trained_adapter_created"] is not False
            or receipt["protected_loader_custody"] is not False
            or receipt["training_lease_established"] is not False
            or type(receipt["optimizer_steps"]) is not int or receipt["optimizer_steps"] != 0
            or type(receipt["forward_passes"]) is not int or receipt["forward_passes"] != 0
            or type(receipt["cpu_float32_parameter_count"]) is not int
            or receipt["cpu_float32_parameter_count"] <= 0):
        raise ModelLoadQualificationError("model-load receipt asserts unsupported state")
    try:
        expected_count = len(json.loads(_MANIFEST.read_text(encoding="utf-8"))["files"])
        expected_sha = hashlib.sha256(_MANIFEST.read_bytes()).hexdigest()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelLoadQualificationError("pinned manifest could not be read") from exc
    if (type(receipt["verified_files"]) is not int
            or receipt["verified_files"] != expected_count
            or receipt["manifest_sha256"] != expected_sha):
        raise ModelLoadQualificationError("model-load receipt has wrong base manifest")
    controls = receipt["effective_controls"]
    if not isinstance(controls, dict) or set(controls) != {
            "memory_max", "memory_high", "swap_max", "cpu_max", "pids_max"}:
        raise ModelLoadQualificationError("missing effective resource-control evidence")
    if (controls["memory_max"] != str(_MEMORY_MAX)
            or controls["memory_high"] != str(_MEMORY_HIGH)
            or controls["swap_max"] != "0" or controls["pids_max"] != str(_PIDS_MAX)):
        raise ModelLoadQualificationError("model-load receipt has invalid resource controls")
    try:
        quota, period = [int(s) for s in controls["cpu_max"].split()]
        if quota <= 0 or period <= 0 or quota * 2 != period:
            raise ModelLoadQualificationError("model-load receipt has invalid CPU cap")
    except (AttributeError, ValueError, TypeError):
        raise ModelLoadQualificationError("model-load receipt CPU cap is malformed") from None
    peak, current = receipt["cgroup_memory_peak_bytes"], receipt["cgroup_memory_current_bytes"]
    if (type(peak) is not int or type(current) is not int
            or not 0 < current <= peak <= _MEMORY_MAX):
        raise ModelLoadQualificationError("model-load memory accounting is invalid")
    return receipt


def _run_parent(base: str | Path) -> dict[str, Any]:
    _controllers_available()
    _private_base(base)
    _available_memory_mib()
    unit = f"aeonith-modelcheck-{os.getpid()}-{secrets.token_hex(12)}.scope"
    try:
        _assert_unloaded(unit)
    except ScopeQualificationError as exc:
        raise ModelLoadQualificationError("disposable scope preflight failed") from exc
    command = [
        "systemd-run", "--user", "--scope", f"--unit={unit}",
        "--property=MemoryMax=4608M", "--property=MemoryHigh=4096M",
        "--property=MemorySwapMax=0", "--property=CPUQuota=50%",
        "--property=TasksMax=64",
        sys.executable, "-m", "experimental.qwen_cpu_load_qualification",
        "--child", "--unit", unit,
        "--base-dir", str(base),
    ]
    failure: ModelLoadQualificationError | None = None
    report: dict[str, Any] | None = None
    try:
        try:
            result = subprocess.run(command, cwd=_REPO_ROOT,
                                    text=True, capture_output=True,
                                    check=False, timeout=_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ModelLoadQualificationError("model-load scope failed or timed out") from exc
        if result.returncode != 0:
            raise ModelLoadQualificationError("bounded model-load child failed; no training")
        receipts = []
        for line in result.stdout.splitlines():
            if not line.startswith("{") or len(line) > 4096:
                continue
            try:
                item = json.loads(line)
            except (ValueError, TypeError):
                raise ModelLoadQualificationError("malformed child receipt") from None
            if isinstance(item, dict) and item.get("schema_version") == "aeonith.qwen_cpu_load_probe.v1":
                receipts.append(item)
        if len(receipts) != 1:
            raise ModelLoadQualificationError("missing unique model-load receipt")
        report = _validate_child_receipt(receipts[0], unit)
    except ModelLoadQualificationError as exc:
        failure = exc
    finally:
        _stop_owned_unit(unit)
        try:
            _assert_unloaded(unit)
        except ScopeQualificationError as exc:
            raise ModelLoadQualificationError("model-load scope remained active") from exc
    if failure is not None:
        raise failure
    assert report is not None
    report["temporary_scope_unloaded"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded Qwen CPU load; NO optimizer or corpus")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--unit", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        if args.execute or not args.unit:
            return 2
        try:
            report = _child_model_load(args.base_dir, args.unit)
        except (ModelLoadQualificationError, ScopeQualificationError):
            return 2
        print(json.dumps(report, sort_keys=True))
        return 0
    if not args.execute or args.unit:
        print(json.dumps({"status": "not_executed", "optimizer_steps": 0}))
        return 2
    try:
        report = _run_parent(args.base_dir)
    except (ModelLoadQualificationError, ScopeQualificationError):
        print("Bounded CPU model-load qualification refused", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
