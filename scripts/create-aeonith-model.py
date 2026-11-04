"""Create Aeonith's untrained, local-only Ollama recipe from an installed base.

Never issues a pull command or remote inference request. A successful create
establishes model packaging, not correctness of generated literary criticism.
The separate Ollama daemon's network behavior cannot be guaranteed by this CLI.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "models" / "aeonith-critic"
RECIPE = PACKAGE / "recipe.json"
ORIGIN = "127.0.0.1"
PORT = 11434


class ModelPackageError(RuntimeError):
    """An explicit local model prerequisite or readback was not satisfied."""


@contextmanager
def _creation_lock(name: str):
    """Serialize cooperating local Aeonith creators, not external Ollama clients.

    An interrupted creator may leave a stale lock. Fail closed rather than
    silently deleting a lock whose ownership cannot be proven.
    """
    name_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
    path = Path(tempfile.gettempdir()) / f"aeonith-model-create-{name_hash}.lock"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ModelPackageError("model creation is already locked; no overwrite attempted") from exc
    except OSError as exc:
        raise ModelPackageError("cannot acquire private model creation lock") from exc
    try:
        created = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        yield
    finally:
        try:
            observed = path.lstat()
            if (not stat.S_ISREG(observed.st_mode)
                    or (observed.st_dev, observed.st_ino) != (created.st_dev, created.st_ino)
                    or observed.st_size != 0):
                raise ModelPackageError("model creation lock identity changed; refusing unrelated unlink")
            path.unlink()
        except OSError as exc:
            raise ModelPackageError("cannot release private model creation lock") from exc


def _json_object(value: bytes) -> dict:
    if len(value) > 2_000_000:
        raise ModelPackageError("local Ollama response exceeded size limit")
    try:
        decoded = json.loads(value)
    except (UnicodeError, ValueError) as exc:
        raise ModelPackageError("local Ollama returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ModelPackageError("local Ollama response was not an object")
    return decoded


def _installed_models() -> dict[str, dict]:
    # http.client goes directly to the numeric loopback socket and never uses
    # inherited HTTP_PROXY or HTTPS_PROXY environment settings.
    connection = http.client.HTTPConnection(ORIGIN, PORT, timeout=5)
    try:
        connection.request("GET", "/api/tags", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ModelPackageError("local Ollama /api/tags is not healthy")
        payload = _json_object(response.read(2_000_001))
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ModelPackageError("local Ollama is unavailable at 127.0.0.1:11434") from exc
    finally:
        connection.close()
    models = payload.get("models")
    if not isinstance(models, list):
        raise ModelPackageError("local Ollama supplied no model inventory")
    inventory = {}
    for row in models:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ModelPackageError("local Ollama model inventory was malformed")
        if row["name"] in inventory:
            raise ModelPackageError("local Ollama model inventory contained duplicate names")
        inventory[row["name"]] = row
    return inventory


def _load_recipe() -> tuple[dict, Path, str]:
    recipe = json.loads(RECIPE.read_text(encoding="utf-8"))
    if recipe.get("schema_version") != "aeonith.model_recipe.v1":
        raise ModelPackageError("unsupported recipe schema")
    base = recipe.get("base", {}).get("name")
    name = recipe.get("name")
    if not isinstance(base, str) or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]+", base) or not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]+", name):
        raise ModelPackageError("invalid model tag in recipe")
    if name == base or recipe.get("fine_tuned") is not False or recipe.get("weights_in_repository") is not False:
        raise ModelPackageError("recipe is not an untrained, distinct local wrapper")
    if recipe.get("local_endpoint") != "http://127.0.0.1:11434":
        raise ModelPackageError("recipe is not restricted to local Ollama")
    if recipe.get("system_prompt") != "request_time_aeonith.core.PROVIDER_INSTRUCTIONS":
        raise ModelPackageError("recipe would override Aeonith's request-time system prompt")
    file_name = recipe.get("modelfile")
    if file_name != "Modelfile":
        raise ModelPackageError("unsupported Modelfile path")
    modelfile = PACKAGE / file_name
    content = modelfile.read_text(encoding="utf-8")
    statements = [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    expected = [
        f"FROM {base}",
        *(f"PARAMETER {key} {value}" for key, value in recipe["limits"].items() if key != "qualified_max_lenses"),
    ]
    if statements != expected:
        raise ModelPackageError("Modelfile disagrees with the versioned recipe")
    return recipe, modelfile, hashlib.sha256(content.encode("utf-8")).hexdigest()


def _run_ollama(*args: str) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("ollama")
    if not binary:
        raise ModelPackageError("Ollama CLI is not installed")
    env = os.environ.copy()
    env.update({"OLLAMA_HOST": "http://127.0.0.1:11434", "OLLAMA_NO_CLOUD": "1", "NO_PROXY": "localhost,127.0.0.1,::1"})
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "OLLAMA_API_KEY"):
        env.pop(name, None)
    try:
        result = subprocess.run(
            [binary, *args], capture_output=True, text=True, check=False,
            env=env, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ModelPackageError("local Ollama command failed or timed out") from exc
    if result.returncode:
        # Do not echo daemon responses, which may contain local filesystem paths.
        raise ModelPackageError(f"local Ollama command exited {result.returncode}")
    return result


def _check_parameters(readback: str, limits: dict) -> None:
    for key, value in limits.items():
        if key == "qualified_max_lenses":
            continue
        pattern = rf"(?mi)^\s*PARAMETER\s+{re.escape(key)}\s+([^\r\n]+?)\s*$"
        observed = re.findall(pattern, readback)
        if not observed:
            raise ModelPackageError(f"created model readback lacks {key}={value}")
        if len(observed) != 1:
            raise ModelPackageError(f"created model readback has ambiguous {key}")
        if observed[0].strip() != str(value):
            raise ModelPackageError(f"created model readback disagrees with {key}={value}")


def _tag(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]+", value))


def build(*, create: bool, base_override: str | None = None) -> dict:
    if create:
        recipe, _, _ = _load_recipe()
        with _creation_lock(recipe["name"]):
            return _build_checked(create=True, base_override=base_override)
    return _build_checked(create=False, base_override=base_override)


def inspect_installed(*, base_override: str | None = None) -> dict:
    """Read back an *existing* local tag without creating or loading a model.

    Ollama tag inventory and Modelfile inspection prove only an observed
    snapshot. They cannot authenticate which base weights the tag was made
    from, whether it was trained, or who owns the checkpoint's rights.
    """
    recipe, modelfile, fingerprint = _load_recipe()
    name = recipe["name"]
    base = recipe["base"]["name"]
    if base_override is not None:
        if not _tag(base_override):
            raise ModelPackageError("--base must name an existing local Ollama tag, not a URL or file path")
        if base_override != base:
            if recipe["base"].get("allow_installed_tag_override") is not True:
                raise ModelPackageError("recipe does not permit a base-model override")
            content = modelfile.read_text(encoding="utf-8")
            replacement = content.replace(f"FROM {base}\n", f"FROM {base_override}\n", 1)
            if replacement == content:
                raise ModelPackageError("cannot safely substitute installed model tag")
            fingerprint = hashlib.sha256(replacement.encode("utf-8")).hexdigest()
            base = base_override

    before = _installed_models()
    if base not in before:
        raise ModelPackageError("required base model is absent; no download attempted")
    if name not in before:
        raise ModelPackageError("target model is absent; no download attempted")
    base_digest = before[base].get("digest")
    model_digest = before[name].get("digest")
    if (not isinstance(base_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", base_digest)
            or not isinstance(model_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", model_digest)):
        raise ModelPackageError("installed model lacks a readable SHA-256 digest")
    readback = _run_ollama("show", "--modelfile", name).stdout
    _check_parameters(readback, recipe["limits"])
    after = _installed_models()
    if (after.get(base, {}).get("digest") != base_digest
            or after.get(name, {}).get("digest") != model_digest):
        raise ModelPackageError("local model digest changed during inspection")
    return {
        "schema_version": "aeonith.local_model_inspection.v1",
        "status": "local_tag_observed_not_provenance_authenticated",
        "model": name,
        "model_digest": model_digest,
        "base": base,
        "base_digest": base_digest,
        "effective_modelfile_sha256": fingerprint,
        "observed_modelfile_sha256": hashlib.sha256(readback.encode("utf-8")).hexdigest(),
        "source_binding": "UNVERIFIED",
        "installed_fine_tuned": "UNKNOWN",
        "base_license_status": recipe["base"]["license_status"],
        "semantic_quality": "UNASSESSED",
        "human_evaluation": "NOT_PERFORMED",
    }


def _build_checked(*, create: bool, base_override: str | None = None) -> dict:
    recipe, modelfile, fingerprint = _load_recipe()
    base = recipe["base"]["name"]
    replacement = None
    if base_override is not None:
        if not _tag(base_override):
            raise ModelPackageError("--base must name an existing local Ollama tag, not a URL or file path")
        if base_override != base:
            if recipe["base"].get("allow_installed_tag_override") is not True:
                raise ModelPackageError("recipe does not permit a base-model override")
            replacement = modelfile.read_text(encoding="utf-8").replace(
                f"FROM {base}\n", f"FROM {base_override}\n", 1,
            )
            if replacement == modelfile.read_text(encoding="utf-8"):
                raise ModelPackageError("cannot safely substitute installed model tag")
            fingerprint = hashlib.sha256(replacement.encode("utf-8")).hexdigest()
            base = base_override
    inventory = _installed_models()
    name = recipe["name"]
    if base not in inventory:
        raise ModelPackageError("required base model is absent; no download attempted")
    base_digest = inventory[base].get("digest")
    if not isinstance(base_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", base_digest):
        raise ModelPackageError("installed base lacks a readable SHA-256 digest")
    if name in inventory:
        raise ModelPackageError("target tag already exists; refusing to overwrite an unrelated model")
    receipt = {
        "schema_version": "aeonith.local_model_receipt.v1",
        "status": "preflight_passed",
        "modelfile_sha256": fingerprint,
        "recipe_manifest_sha256": hashlib.sha256(RECIPE.read_bytes()).hexdigest(),
        "model": name,
        "base": base,
        "base_digest": base_digest,
        "base_license_status": recipe["base"]["license_status"],
        "fine_tuned": False,
        "quality_qualified": False,
    }
    if not create:
        return receipt
    if replacement is None:
        _run_ollama("create", name, "-f", str(modelfile))
    else:
        # The checked override is deliberately ephemeral: source controls
        # stay unchanged and no Hugging Face / Ollama download is requested.
        with tempfile.TemporaryDirectory(prefix="aeonith-local-model-") as temporary:
            selected_file = Path(temporary) / "Modelfile"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(selected_file, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(replacement)
            _run_ollama("create", name, "-f", str(selected_file))
    observed = _installed_models().get(name)
    if observed is None or not isinstance(observed.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", observed["digest"]):
        raise ModelPackageError("created model did not appear with an observable digest")
    readback = _run_ollama("show", "--modelfile", name).stdout
    _check_parameters(readback, recipe["limits"])
    receipt.update({"status": "created_and_read_back", "model_digest": observed["digest"]})
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--check", action="store_true", help="Read-only, verify installed base and safe recipe")
    choices.add_argument("--create", action="store_true", help="Create a new derived local tag; never overwrite")
    choices.add_argument("--inspect", action="store_true", help="Read-only inspection of an existing target tag and safe parameter snapshot")
    parser.add_argument("--base", help="Override the recipe's base with an already-installed local Ollama tag; never downloads")
    args = parser.parse_args(argv)
    try:
        receipt = (inspect_installed(base_override=args.base) if args.inspect
                   else build(create=args.create, base_override=args.base))
    except (ModelPackageError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        print(f"Aeonith model package: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
