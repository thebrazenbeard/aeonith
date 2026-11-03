"""Offline, source-only PEFT-to-GGUF handoff for a pinned Qwen3.5 base.

This module NEVER invokes a converter. It checks locally supplied artifact
fingerprints and writes an explicitly unexecuted, private command recipe.
The existence of that recipe is not evidence of a compatible GGUF artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from aeonith.private_output import PrivateOutputError, create_private_directory

from .corpus import CorpusError
from .train_lora import _output_path
from .verify_adapter import VerificationError, inspect_adapter_receipt
from .verify_base import BaseVerificationError, verify_checkpoint


class HandoffError(ValueError):
    """Inputs are unsafe or insufficient to construct a local handoff."""


REPO_ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_CONVERTER_BYTES = 2 * 1024 * 1024


def _require_private_directory_permissions() -> None:
    """Windows needs a qualified handle-pinned writer, not mkdir mode alone."""
    if sys.platform == "win32" or os.name == "nt":
        raise HandoffError(
            "Windows private GGUF recipe ACL and handle-relative writes are not yet qualified; "
            "read-only inspection remains available"
        )


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local(value: str | Path, name: str) -> Path:
    raw = Path(value).expanduser().absolute()
    if any(part == ".." for part in raw.parts):
        raise HandoffError(f"{name} must not contain traversal")
    if os.name == "nt" and str(raw).startswith("\\\\"):
        raise HandoffError(f"{name} cannot be a UNC path")
    for item in (raw, *raw.parents):
        if item.is_symlink() or bool(getattr(item, "is_junction", lambda: False)()):
            raise HandoffError(f"{name} cannot use symlinks or junctions")
    resolved = raw.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise HandoffError(f"{name} must remain outside the Aeonith checkout")
    return resolved


def inspect_handoff(base: str | Path, adapter: str | Path, receipt: str | Path,
                    expected_base_manifest: str | Path, converter: str | Path,
                    converter_sha256: str) -> tuple[dict[str, Any], dict[str, Path]]:
    """Check exact local bytes, returning a text-free receipt and private paths.

    The expected file manifest and converter digest are operator supplied;
    neither identifies an authenticated publisher or qualified converter.
    """
    paths = {
        "base": _local(base, "base checkpoint"),
        "adapter": _local(adapter, "adapter"),
        "receipt": _local(receipt, "training receipt"),
        "expected_base_manifest": _local(expected_base_manifest, "base manifest"),
        "converter": _local(converter, "converter"),
    }
    if not isinstance(converter_sha256, str) or not HEX64.fullmatch(converter_sha256):
        raise HandoffError("expected converter SHA-256 must be 64 lowercase hex digits")
    script = paths["converter"]
    if script.name != "convert_lora_to_gguf.py" or not script.is_file() or not 0 < script.stat().st_size <= MAX_CONVERTER_BYTES:
        raise HandoffError("locally pinned convert_lora_to_gguf.py is required")
    if _digest(script) != converter_sha256:
        raise HandoffError("local converter fingerprint mismatch")
    try:
        adapter_check = inspect_adapter_receipt(paths["base"], paths["adapter"], paths["receipt"])
        base_check = verify_checkpoint(
            paths["base"], paths["expected_base_manifest"],
            expected_model=adapter_check["base_model_id"],
            expected_revision=adapter_check["base_revision_declared_not_remote_verified"],
        )
    except (VerificationError, BaseVerificationError, OSError) as exc:
        raise HandoffError("base/adapter files do not match both local receipts") from exc
    result = {
        "schema_version": "aeonith.gguf_handoff_check.v1",
        "status": "matching_local_artifacts_recipe_only_not_converted",
        "base_model_id": adapter_check["base_model_id"],
        "base_revision_declared_not_remote_verified": adapter_check["base_revision_declared_not_remote_verified"],
        "base_manifest_sha256": base_check["expected_manifest_sha256"],
        "training_receipt_sha256": adapter_check["receipt_sha256"],
        "adapter_files": [
            {"name": filename, "sha256": _digest(paths["adapter"] / filename)}
            for filename in ("adapter_config.json", "adapter_model.safetensors")
        ],
        "converter_sha256": converter_sha256,
        "adapter_fingerprints_match_receipt": True,
        "base_fingerprints_match_manifest": True,
        "upstream_origin_authenticated": False,
        "converter_provenance_authenticated": False,
        "qwen35_lora_gguf_conversion_compatibility_qualified": False,
        "gguf_artifact_created": False,
        "literary_quality_qualified": False,
        "limitations": [
            "the supplied expected-file and converter hashes are not independently authenticated",
            "the converter has not been executed and no GGUF file exists from this procedure",
            "Qwen3.5 text-tower adapter mapping, base GGUF identity and KoboldCpp loading are untested",
            "published adapters require separate rights and artifact approval",
        ],
    }
    return result, paths


def prepare_handoff(base: str | Path, adapter: str | Path, receipt: str | Path,
                    expected_base_manifest: str | Path, converter: str | Path,
                    converter_sha256: str, output: str | Path) -> dict[str, Any]:
    """Create a private, non-executable recipe in a new empty directory."""
    result, paths = inspect_handoff(base, adapter, receipt, expected_base_manifest,
                                    converter, converter_sha256)
    destination = _local(output, "output directory")
    if destination.exists() or not destination.parent.is_dir():
        raise HandoffError("output must be a new directory under an existing private parent")
    if any(destination == item or item in destination.parents or destination in item.parents
           for item in paths.values()):
        raise HandoffError("output must not overlap a model artifact or evidence file")
    # A private plan contains sensitive absolute checkpoint paths. Reject any
    # unrelated checkout, linked worktree or bare Git repository before the
    # descriptor-pinned POSIX writer performs its own parent walk.
    try:
        _output_path(str(destination))
    except CorpusError as exc:
        if "outside Git checkouts" in str(exc):
            raise HandoffError("private GGUF plans must be outside Git checkouts") from exc
        raise HandoffError("private GGUF output path is unsafe or unavailable") from exc
    _require_private_directory_permissions()
    # The adapter GGUF is intentionally NOT made here. The explicit --base
    # prevents llama.cpp converter's Hub fallback, but this command must still
    # be independently reviewed against the exact local converter revision.
    recipe = {
        **result,
        "schema_version": "aeonith.gguf_handoff_plan.v1",
        "status": "private_recipe_prepared_not_executed",
        "conversion_env": {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                           "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"},
        "conversion_argv_not_executed": [
            sys.executable, str(paths["converter"]), "--base", str(paths["base"]),
            "--outfile", str(destination / "aeonith-adapter-f16.gguf"),
            "--outtype", "f16", str(paths["adapter"]),
        ],
        "base_gguf": "REQUIRES_SEPARATE_TRUSTED_MATCHING_BASE_GGUF",
        "conversion_operator_approval_required": True,
        "runtime_loading_test_required": True,
    }
    # Exclusive, descriptor-pinned private directory/file writes on POSIX.
    # A partial directory after a crash stays visible and non-overwritable.
    payload = (json.dumps(recipe, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with create_private_directory(str(destination)) as private:
            private.write_bytes("handoff_plan.json", payload)
    except (PrivateOutputError, OSError) as exc:
        raise HandoffError("private GGUF recipe creation could not be safely established") from exc
    return {**result, "status": "private_recipe_prepared_not_executed",
            "handoff_plan_sha256": hashlib.sha256(payload).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, source-only GGUF LoRA handoff; does not convert weights")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--converter-sha256", required=True)
    parser.add_argument("--output", type=Path, help="new private directory for an unexecuted plan")
    parser.add_argument("--prepare", action="store_true", help="explicitly write a private recipe; never run conversion")
    args = parser.parse_args(argv)
    try:
        if bool(args.output) != args.prepare:
            parser.error("--prepare and --output must be supplied together")
        if args.prepare:
            report = prepare_handoff(args.base, args.adapter, args.receipt,
                                     args.base_manifest, args.converter,
                                     args.converter_sha256, args.output)
        else:
            report, _ = inspect_handoff(args.base, args.adapter, args.receipt,
                                        args.base_manifest, args.converter, args.converter_sha256)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (HandoffError, OSError) as exc:
        print(f"GGUF handoff unavailable: {exc if isinstance(exc, HandoffError) else 'filesystem access failed'}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
