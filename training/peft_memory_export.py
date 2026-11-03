"""Opt-in path-free PEFT adapter serialization into the pinned Linux broker.

This exports an *already-trained* model's adapter. It does not run an optimizer,
validate data rights, authenticate weights, or enable the gated trainers.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import hashlib
import json
from typing import Any

from aeonith.private_output import MAX_PRIVATE_FILE_BYTES, PrivateOutputError
from .private_artifact_broker import PinnedTrainingArtifacts


MAX_CONFIG_BYTES = 64 * 1024


def _json_value(value: Any) -> Any:
    """Convert PEFT's Enum/set config fields without silently losing fields."""
    if isinstance(value, Enum):
        return _json_value(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    raise PrivateOutputError("unsupported PEFT configuration field type")


def export_peft_adapter_to_broker(model: Any, broker: PinnedTrainingArtifacts, *,
                                  adapter_name: str = "default") -> dict[str, Any]:
    """Serialize a default LoRA adapter in memory and save via pinned FDs.

    The caller must have separately authenticated the model, completed and
    witnessed a gradient update, and established rights and a host lease. This
    function does *none* of those things. Files are exclusive but the two-file
    bundle is not atomic; partial exports remain private for inspection.
    """
    if adapter_name != "default":
        raise PrivateOutputError("only default PEFT adapter export is supported")
    broker.verify_live()
    configs = getattr(model, "peft_config", None)
    if not isinstance(configs, Mapping) or adapter_name not in configs:
        raise PrivateOutputError("PEFT model lacks default adapter configuration")
    config = configs[adapter_name]
    if not callable(getattr(config, "to_dict", None)):
        raise PrivateOutputError("PEFT adapter configuration cannot be serialized")
    raw = config.to_dict()
    if not isinstance(raw, Mapping):
        raise PrivateOutputError("invalid PEFT adapter configuration")
    normalized = _json_value(raw)
    if normalized.get("peft_type") != "LORA" or normalized.get("task_type") != "CAUSAL_LM":
        raise PrivateOutputError("only causal LM LoRA PEFT adapters are supported")
    normalized["inference_mode"] = True
    try:
        config_bytes = (json.dumps(normalized, indent=2, sort_keys=True,
                                   allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PrivateOutputError("invalid PEFT adapter configuration JSON") from exc
    if not 0 < len(config_bytes) <= MAX_CONFIG_BYTES:
        raise PrivateOutputError("PEFT adapter configuration exceeds private export limit")

    try:
        from peft import get_peft_model_state_dict
        from safetensors.torch import save as safetensors_save
    except ImportError as exc:
        raise PrivateOutputError("local PEFT and safetensors are required for adapter serialization") from exc
    state = get_peft_model_state_dict(model, adapter_name=adapter_name)
    if not isinstance(state, Mapping) or not state:
        raise PrivateOutputError("PEFT returned an empty or invalid adapter state")
    tensors: dict[str, Any] = {}
    for name, tensor in state.items():
        if not isinstance(name, str) or not name or name in tensors:
            raise PrivateOutputError("PEFT adapter tensor name is invalid")
        try:
            tensors[name] = tensor.detach().to(device="cpu").contiguous()
        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            raise PrivateOutputError("PEFT adapter tensor cannot be serialized") from exc
    try:
        weights = safetensors_save(tensors)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise PrivateOutputError("safetensors adapter serialization failed") from exc
    if not isinstance(weights, bytes) or not 0 < len(weights) <= MAX_PRIVATE_FILE_BYTES:
        raise PrivateOutputError("serialized PEFT adapter is empty or exceeds private export limit")

    # Both payloads are complete before the first output file is created.
    # The config is written last: a truncated export cannot present a
    # complete pair, and the broker never overwrites existing bytes.
    broker.write_adapter_bytes("adapter_model.safetensors", weights)
    broker.write_adapter_bytes("adapter_config.json", config_bytes)
    return {
        "schema_version": "aeonith.peft_pinned_export.v1",
        "status": "adapter_bytes_exported_not_training_qualified",
        "adapter_name": adapter_name,
        "tensors_exported": len(tensors),
        "files": [
            {"path": "adapter_config.json", "bytes": len(config_bytes),
             "sha256": hashlib.sha256(config_bytes).hexdigest()},
            {"path": "adapter_model.safetensors", "bytes": len(weights),
             "sha256": hashlib.sha256(weights).hexdigest()},
        ],
        "fresh_process_reload_qualified": False,
        "gradient_update_verified": False,
        "optimizer_start_authorized": False,
    }
