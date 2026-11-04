"""Offline tests for the versioned local-only model recipe and installer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create-aeonith-model.py"
SPEC = importlib.util.spec_from_file_location("aeonith_model_installer", SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)

BASE_DIGEST = "a" * 64
MODEL_DIGEST = "b" * 64
BASE = "qwen2.5-coder:1.5b-instruct-q3_K_M"
TARGET = "aeonith-critic:0.1"


class LocalModelPackageTests(unittest.TestCase):
    def test_recipe_is_untrained_local_only_and_matches_modelfile(self):
        recipe, file, digest = installer._load_recipe()
        self.assertEqual(TARGET, recipe["name"])
        self.assertEqual(BASE, recipe["base"]["name"])
        self.assertFalse(recipe["fine_tuned"])
        self.assertFalse(recipe["weights_in_repository"])
        self.assertFalse(recipe["quality_qualified"])
        self.assertIsNone(recipe["base"]["digest"])
        self.assertEqual("unverified_local_variant", recipe["base"]["license_status"])
        self.assertEqual(64, len(digest))
        contents = file.read_text(encoding="utf-8")
        self.assertNotIn("\nSYSTEM", contents)
        self.assertNotIn("ollama pull", contents.lower())
        self.assertNotIn("https://", contents)

    def test_missing_base_refuses_creation_and_never_calls_cli(self):
        with patch.object(installer, "_installed_models", return_value={}):
            with patch.object(installer, "_run_ollama") as run:
                with self.assertRaisesRegex(installer.ModelPackageError, "base model is absent"):
                    installer.build(create=True)
                run.assert_not_called()

    def test_existing_target_refuses_overwrite(self):
        inventory = {BASE: {"digest": BASE_DIGEST}, TARGET: {"digest": MODEL_DIGEST}}
        with patch.object(installer, "_installed_models", return_value=inventory):
            with patch.object(installer, "_run_ollama") as run:
                with self.assertRaisesRegex(installer.ModelPackageError, "refusing to overwrite"):
                    installer.build(create=True)
                run.assert_not_called()

    def test_parallel_creator_lock_fails_closed_before_model_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(installer.tempfile, "gettempdir", return_value=temp):
                with installer._creation_lock(TARGET):
                    with patch.object(installer, "_installed_models") as inventory, \
                         patch.object(installer, "_run_ollama") as run:
                        with self.assertRaisesRegex(installer.ModelPackageError, "already locked"):
                            installer.build(create=True)
                        inventory.assert_not_called()
                        run.assert_not_called()

    def test_creator_never_unlinks_a_replaced_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(installer.tempfile, "gettempdir", return_value=temp):
                lock = Path(temp) / (
                    "aeonith-model-create-"
                    + installer.hashlib.sha256(TARGET.encode("utf-8")).hexdigest()[:24]
                    + ".lock"
                )
                with self.assertRaisesRegex(installer.ModelPackageError, "lock identity changed"):
                    with installer._creation_lock(TARGET):
                        lock.unlink()
                        lock.write_text("foreign replacement; preserve", encoding="utf-8")
                self.assertEqual(lock.read_text(encoding="utf-8"),
                                 "foreign replacement; preserve")

    def test_check_only_reports_base_fingerprint_without_mutation(self):
        with patch.object(installer, "_installed_models", return_value={BASE: {"digest": BASE_DIGEST}}):
            with patch.object(installer, "_run_ollama") as run:
                value = installer.build(create=False)
                run.assert_not_called()
        self.assertEqual("preflight_passed", value["status"])
        self.assertEqual(BASE_DIGEST, value["base_digest"])
        self.assertNotIn("model_digest", value)
        self.assertFalse(value["fine_tuned"])
        self.assertFalse(value["quality_qualified"])
        self.assertEqual(64, len(value["modelfile_sha256"]))
        self.assertEqual(64, len(value["recipe_manifest_sha256"]))

    def test_override_requires_an_existing_local_tag_without_download(self):
        candidate = "granite-literary:local"
        with patch.object(installer, "_installed_models", return_value={candidate: {"digest": BASE_DIGEST}}):
            with patch.object(installer, "_run_ollama") as run:
                receipt = installer.build(create=False, base_override=candidate)
                run.assert_not_called()
        self.assertEqual(candidate, receipt["base"])
        self.assertNotEqual(installer._load_recipe()[2], receipt["modelfile_sha256"])
        with patch.object(installer, "_installed_models", return_value={}):
            with patch.object(installer, "_run_ollama") as run:
                with self.assertRaisesRegex(installer.ModelPackageError, "base model is absent"):
                    installer.build(create=True, base_override=candidate)
                run.assert_not_called()
        for bad in ("https://huggingface.co/owner/model", "../model.gguf", "", "bad name"):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(installer.ModelPackageError, "existing local Ollama tag"):
                    installer.build(create=False, base_override=bad)

    def test_override_creates_from_temporary_modelfile_without_changing_source(self):
        candidate = "granite-literary:local"
        before_content = (installer.PACKAGE / "Modelfile").read_text(encoding="utf-8")
        captured = []

        def fake_run(*args):
            if args[0] == "create":
                path = Path(args[3])
                captured.append(path.read_text(encoding="utf-8"))
                return subprocess.CompletedProcess([], 0, "", "")
            return subprocess.CompletedProcess([], 0, "PARAMETER num_ctx 4096\nPARAMETER temperature 0.2\nPARAMETER num_predict 800\n", "")

        before = {candidate: {"digest": BASE_DIGEST}}
        after = {**before, TARGET: {"digest": MODEL_DIGEST}}
        with patch.object(installer, "_installed_models", side_effect=[before, after]):
            with patch.object(installer, "_run_ollama", side_effect=fake_run):
                result = installer.build(create=True, base_override=candidate)
        self.assertEqual("created_and_read_back", result["status"])
        self.assertIn("FROM granite-literary:local\n", captured[0])
        self.assertEqual(before_content, (installer.PACKAGE / "Modelfile").read_text(encoding="utf-8"))

    def test_create_requires_actual_inventory_and_modelfile_readback(self):
        inventory_before = {BASE: {"digest": BASE_DIGEST}}
        inventory_after = {**inventory_before, TARGET: {"digest": MODEL_DIGEST}}
        readback = subprocess.CompletedProcess(
            args=["ollama", "show"], returncode=0,
            stdout="FROM /local/sha256-abc\nPARAMETER num_ctx 4096\nPARAMETER temperature 0.2\nPARAMETER num_predict 800\n",
            stderr="",
        )
        created = subprocess.CompletedProcess(args=["ollama", "create"], returncode=0, stdout="", stderr="")
        with patch.object(installer, "_installed_models", side_effect=[inventory_before, inventory_after]):
            with patch.object(installer, "_run_ollama", side_effect=[created, readback]) as run:
                receipt = installer.build(create=True)
        self.assertEqual("created_and_read_back", receipt["status"])
        self.assertEqual(MODEL_DIGEST, receipt["model_digest"])
        self.assertFalse(receipt["fine_tuned"])
        self.assertFalse(receipt["quality_qualified"])
        self.assertEqual(("create", TARGET, "-f", str(installer.PACKAGE / "Modelfile")), run.call_args_list[0].args)
        self.assertEqual(("show", "--modelfile", TARGET), run.call_args_list[1].args)

    def test_create_fails_if_generated_model_is_not_observed(self):
        before = {BASE: {"digest": BASE_DIGEST}}
        with patch.object(installer, "_installed_models", side_effect=[before, before]):
            with patch.object(installer, "_run_ollama", return_value=subprocess.CompletedProcess([], 0, "", "")):
                with self.assertRaisesRegex(installer.ModelPackageError, "did not appear"):
                    installer.build(create=True)

    def test_create_fails_if_readback_lacks_safety_limits(self):
        before = {BASE: {"digest": BASE_DIGEST}}
        after = {**before, TARGET: {"digest": MODEL_DIGEST}}
        with patch.object(installer, "_installed_models", side_effect=[before, after]):
            with patch.object(installer, "_run_ollama", side_effect=[
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "PARAMETER temperature 0.2\n", ""),
            ]):
                with self.assertRaisesRegex(installer.ModelPackageError, "readback lacks num_ctx"):
                    installer.build(create=True)

    def test_inspect_existing_local_tag_is_read_only_and_explicitly_unbound(self):
        replacement = "qwen3:1.7b"
        local = {replacement: {"digest": BASE_DIGEST}, TARGET: {"digest": MODEL_DIGEST}}
        readback = subprocess.CompletedProcess([], 0,
            "FROM /blobs/sha256-opaque\nPARAMETER num_ctx 4096\n"
            "PARAMETER temperature 0.2\nPARAMETER num_predict 800\n", "")
        with patch.object(installer, "_installed_models", side_effect=[local, local]) as tags, \
             patch.object(installer, "_run_ollama", return_value=readback) as cmd:
            receipt = installer.inspect_installed(base_override=replacement)
        self.assertEqual(tags.call_count, 2)
        cmd.assert_called_once_with("show", "--modelfile", TARGET)
        self.assertEqual(receipt["status"], "local_tag_observed_not_provenance_authenticated")
        self.assertEqual(receipt["model_digest"], MODEL_DIGEST)
        self.assertEqual(receipt["base_digest"], BASE_DIGEST)
        self.assertEqual(receipt["source_binding"], "UNVERIFIED")
        self.assertEqual(receipt["installed_fine_tuned"], "UNKNOWN")
        self.assertEqual(receipt["semantic_quality"], "UNASSESSED")
        self.assertNotIn("/blobs/", json.dumps(receipt))

    def test_inspect_rejects_changed_or_missing_target_digest(self):
        before = {BASE: {"digest": BASE_DIGEST}, TARGET: {"digest": MODEL_DIGEST}}
        changed = {BASE: {"digest": BASE_DIGEST}, TARGET: {"digest": "c" * 64}}
        readback = subprocess.CompletedProcess([], 0,
            "PARAMETER num_ctx 4096\nPARAMETER temperature 0.2\nPARAMETER num_predict 800\n", "")
        with patch.object(installer, "_installed_models", side_effect=[before, changed]), \
             patch.object(installer, "_run_ollama", return_value=readback):
            with self.assertRaisesRegex(installer.ModelPackageError, "changed during inspection"):
                installer.inspect_installed()
        with patch.object(installer, "_installed_models", return_value={BASE: {"digest": BASE_DIGEST}}), \
             patch.object(installer, "_run_ollama") as cmd:
            with self.assertRaisesRegex(installer.ModelPackageError, "target model is absent"):
                installer.inspect_installed()
            cmd.assert_not_called()

    def test_duplicate_conflicting_parameter_readback_is_not_proof(self):
        ambiguous = ("PARAMETER num_ctx 4096\nPARAMETER num_ctx 8192\n"
                     "PARAMETER temperature 0.2\nPARAMETER num_predict 800\n")
        with self.assertRaisesRegex(installer.ModelPackageError, "ambiguous num_ctx"):
            installer._check_parameters(ambiguous, installer._load_recipe()[0]["limits"])

    def test_malformed_inventory_and_proxied_environment_never_get_remote_targets(self):
        class FakeResponse:
            status = 200
            def read(self, _limit):
                return json.dumps({"models": [{"name": BASE}, {"name": BASE}]}).encode("utf-8")

        class FakeConnection:
            def __init__(self, host, port, timeout):
                self.asserts = (host, port, timeout)
            def request(self, method, path, headers):
                self.requested = (method, path, headers)
            def getresponse(self):
                return FakeResponse()
            def close(self):
                pass

        with patch.object(installer.http.client, "HTTPConnection", FakeConnection):
            with self.assertRaisesRegex(installer.ModelPackageError, "duplicate names"):
                installer._installed_models()

        run = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(installer.shutil, "which", return_value="/bin/ollama"):
            with patch.object(installer.subprocess, "run", return_value=run) as process:
                with patch.dict(installer.os.environ, {"OLLAMA_HOST": "https://other.host", "HTTP_PROXY": "http://proxy.invalid", "OLLAMA_API_KEY": "secret"}):
                    installer._run_ollama("show", "--modelfile", TARGET)
        self.assertEqual(["/bin/ollama", "show", "--modelfile", TARGET], process.call_args.args[0])
        env = process.call_args.kwargs["env"]
        self.assertEqual("http://127.0.0.1:11434", env["OLLAMA_HOST"])
        self.assertEqual("1", env["OLLAMA_NO_CLOUD"])
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("OLLAMA_API_KEY", env)


if __name__ == "__main__":
    unittest.main()
