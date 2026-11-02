"""Offline and synthetic-only tests for paired, work-isolated model evaluations."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evaluation.paired_model_bench import BenchError, prepare
from evaluation.quality_eval import build_blind_pair, digest, make_manifest


BASE_SHA = "a" * 64
ADAPTER_SHA = "b" * 64


def request(work: str) -> dict:
    return {"schema_version": "aeonith.review.v1", "work": {"text": work},
            "lenses": ["symbolic"]}


def review(work: str, marker: str) -> dict:
    return {
        "schema_version": "aeonith.review.v1", "status": "completed",
        "assessment": None,
        "lens_reviews": [{"lens": "symbolic", "analysis": f"{marker}: the threshold invites uncertainty.",
                          "basis": "textual", "support": [{"source": "work", "quote": "gate"}],
                          "limitations": ["The narrator's intention is unknown."]}],
        "synthesis": f"{marker}: no single allegory is established.",
        "challenges": [], "uncertainties": ["Who closed the gate is unclear."],
    }


def model_manifest(req: dict, output: dict, model: str, seed: int) -> dict:
    return make_manifest(req, output, provider_id="operator-declared-offline",
                         model_id=model, code_revision="source-rev-1", prompt_revision="prompt-v1",
                         parameters={"seed": seed, "temperature": 0})


def payload() -> dict:
    training = "Training material: the gate was locked."
    validation = "Validation material: a gate was repainted."
    works = {
        "fresh-one": "Ada stood by the blue gate.",
        "fresh-two": "Bela left the red gate open.",
    }
    experiment = {
        "schema_version": "aeonith.paired_model_bench.v1",
        "experiment_id": "fixture-comparison-01",
        "model_identities": {
            "base": {"model_id": "unchanged-base", "weights_sha256": BASE_SHA},
            "adapter": {"model_id": "trained-adapter", "weights_sha256": ADAPTER_SHA},
        },
        "split_inventory": {
            "train": [{"source_id": "train-one", "work_sha256": digest(training)}],
            "validation": [{"source_id": "dev-one", "work_sha256": digest(validation)}],
            "holdout": [{"source_id": identity, "work_sha256": digest(work)}
                        for identity, work in works.items()],
        },
        "runs": [],
    }
    for source_id, text in works.items():
        for seed in (11, 29):
            req = request(text)
            first = review(text, f"Frozen {seed}")
            second = review(text, f"Adapter {seed}")
            experiment["runs"].append({
                "source_id": source_id, "seed": seed, "request": req,
                "base_review": first, "adapter_review": second,
                "base_manifest": model_manifest(req, first, "unchanged-base", seed),
                "adapter_manifest": model_manifest(req, second, "trained-adapter", seed),
            })
    return experiment


class PairedModelBenchTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.input = self.root / "private.json"
        self.out = self.root / "private-pairs"
        self.data = payload()

    def write(self) -> None:
        self.input.write_text(json.dumps(self.data), encoding="utf-8")

    def test_outputs_private_blinded_pairs_keys_and_redacted_receipt(self) -> None:
        self.write()
        receipt = prepare(self.input, self.out)
        self.assertEqual(receipt["status"], "paired_run_validated_not_quality_qualified")
        self.assertEqual(receipt["run_count"], 4)
        self.assertEqual(receipt["blinded_pair_count"], 4)
        self.assertEqual(receipt["distinct_holdout_work_count"], 2)
        self.assertEqual(receipt["seed_count"], 2)
        self.assertFalse(receipt["model_execution_authenticated"])
        self.assertFalse(receipt["holdout_custody_independently_verified"])
        self.assertNotIn("Ada stood", json.dumps(receipt))
        self.assertNotIn("Frozen 11", json.dumps(receipt))
        self.assertEqual(len(list((self.out / "pairs").glob("*.json"))), 4)
        self.assertEqual(len(list((self.out / "keys").glob("*.json"))), 4)
        pair = json.loads(next((self.out / "pairs").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(set(pair), {"schema_version", "pair_id", "request", "A", "B", "directions"})
        self.assertNotIn("unchanged-base", json.dumps(pair))
        self.assertNotIn("trained-adapter", json.dumps(pair))
        self.assertTrue((self.out / "bench_receipt.json").is_file())

    def test_identical_outputs_across_seeds_get_unique_aligned_pair_ids_even_if_order_flips(self) -> None:
        source = "fresh-one"
        representative = next(run for run in self.data["runs"] if run["source_id"] == source)
        base, adapter = representative["base_review"], representative["adapter_review"]
        orientations: dict[bool, int] = {}
        for seed in range(1, 100):
            run_id = digest({"source_id": source, "seed": seed})[:24]
            _, key = build_blind_pair(representative["request"], base, adapter,
                                      "unchanged-base", "trained-adapter",
                                      seed=f"fixture-comparison-01:{seed}:{run_id}")
            orientations.setdefault(key["flipped"], seed)
            if len(orientations) == 2:
                break
        self.assertEqual(len(orientations), 2, "the fixture must exercise opposite A/B orientations")
        seeds = list(orientations.values())
        for group_source in ("fresh-one", "fresh-two"):
            group = [item for item in self.data["runs"] if item["source_id"] == group_source]
            first = group[0]
            for index, item in enumerate(group):
                item["seed"] = seeds[index]
                item["base_review"] = deepcopy(first["base_review"])
                item["adapter_review"] = deepcopy(first["adapter_review"])
                item["base_manifest"] = model_manifest(item["request"], item["base_review"],
                                                       "unchanged-base", item["seed"])
                item["adapter_manifest"] = model_manifest(item["request"], item["adapter_review"],
                                                          "trained-adapter", item["seed"])
        self.write()
        receipt = prepare(self.input, self.out)
        self.assertEqual(receipt["repeated_content_pair_count"], 2)
        self.assertEqual(len({row["pair_id"] for row in receipt["runs"]}), 4)
        for pair_path in (self.out / "pairs").glob("*.json"):
            key_path = self.out / "keys" / pair_path.name
            pair = json.loads(pair_path.read_text(encoding="utf-8"))
            key = json.loads(key_path.read_text(encoding="utf-8"))
            self.assertEqual(pair["pair_id"], key["pair_id"])
            self.assertNotEqual(pair["pair_id"], key["source_content_pair_id"])
        first_keys = [json.loads(path.read_text(encoding="utf-8"))
                      for path in (self.out / "keys").glob("*.json")]
        identical_groups: dict[str, list[dict]] = {}
        for key in first_keys:
            identical_groups.setdefault(key["source_content_pair_id"], []).append(key)
        self.assertEqual(sorted(len(group) for group in identical_groups.values()), [2, 2])
        self.assertTrue(any(group[0]["flipped"] != group[1]["flipped"]
                            for group in identical_groups.values()))

    def test_rejects_train_or_validation_source_overlap(self) -> None:
        self.data["split_inventory"]["train"][0]["source_id"] = "fresh-one"
        self.write()
        with self.assertRaisesRegex(BenchError, "split overlap"):
            prepare(self.input, self.out)
        self.assertFalse(self.out.exists())

    def test_official_slash_qualified_base_model_name_is_supported(self) -> None:
        official_id = "Qwen/Qwen3.5-0.8B"
        self.data["model_identities"]["base"]["model_id"] = official_id
        for item in self.data["runs"]:
            item["base_manifest"]["model_id"] = official_id
        self.write()
        receipt = prepare(self.input, self.out)
        self.assertEqual(receipt["blinded_pair_count"], 4)
        self.assertTrue((self.out / "bench_receipt.json").is_file())

    def test_rejects_matching_work_text_hash_with_different_source_ids(self) -> None:
        holdout_hash = self.data["split_inventory"]["holdout"][0]["work_sha256"]
        self.data["split_inventory"]["validation"][0]["work_sha256"] = holdout_hash
        self.write()
        with self.assertRaisesRegex(BenchError, "split overlap"):
            prepare(self.input, self.out)

    def test_rejects_tampered_output_manifest_or_seed(self) -> None:
        original = deepcopy(self.data)
        for change in ("output_sha256", "seed", "model_id"):
            with self.subTest(change=change):
                self.data = deepcopy(original)
                manifest = self.data["runs"][0]["base_manifest"]
                if change == "output_sha256":
                    manifest[change] = "0" * 64
                elif change == "seed":
                    manifest["parameters"]["seed"] = 3
                else:
                    manifest["model_id"] = "unknown-model"
                self.write()
                with self.assertRaisesRegex(BenchError, "manifest"):
                    prepare(self.input, self.out)
                self.assertFalse(self.out.exists())

    def test_rejects_missing_seed_or_duplicate_run(self) -> None:
        self.data["runs"].pop()
        self.write()
        with self.assertRaisesRegex(BenchError, "seed"):
            prepare(self.input, self.out)
        self.data = payload()
        self.data["runs"].append(deepcopy(self.data["runs"][0]))
        self.write()
        with self.assertRaisesRegex(BenchError, "duplicate"):
            prepare(self.input, self.out)

    def test_rejects_unfair_comparison_settings_or_drift_across_runs(self) -> None:
        original = deepcopy(self.data)
        for change in ("adapter_temperature", "adapter_prompt", "second_run_temperature"):
            with self.subTest(change=change):
                self.data = deepcopy(original)
                if change == "adapter_temperature":
                    self.data["runs"][0]["adapter_manifest"]["parameters"]["temperature"] = 0.7
                elif change == "adapter_prompt":
                    self.data["runs"][0]["adapter_manifest"]["prompt_revision"] = "different-prompt"
                else:
                    for name in ("base_manifest", "adapter_manifest"):
                        self.data["runs"][1][name]["parameters"]["temperature"] = 0.7
                self.write()
                with self.assertRaisesRegex(BenchError, "comparison settings"):
                    prepare(self.input, self.out)
                self.assertFalse(self.out.exists())

    def test_invalid_model_review_is_counted_not_silently_excluded(self) -> None:
        bad = self.data["runs"][0]
        bad["adapter_review"]["lens_reviews"][0]["support"][0]["quote"] = "never occurred"
        bad["adapter_manifest"] = model_manifest(bad["request"], bad["adapter_review"], "trained-adapter", 11)
        self.write()
        receipt = prepare(self.input, self.out)
        self.assertEqual(receipt["run_count"], 4)
        self.assertEqual(receipt["blinded_pair_count"], 3)
        self.assertEqual(receipt["adapter_structural_failures"], 1)
        self.assertEqual(receipt["base_structural_failures"], 0)

    def test_failed_model_response_is_not_semantic_quality_result(self) -> None:
        item = self.data["runs"][0]
        item["base_review"] = {"status": "provider_unavailable"}
        item["base_manifest"] = model_manifest(item["request"], item["base_review"], "unchanged-base", 11)
        self.write()
        receipt = prepare(self.input, self.out)
        self.assertEqual(receipt["base_not_evaluable"], 1)
        self.assertEqual(receipt["blinded_pair_count"], 3)

    def test_output_cannot_overwrite_or_target_checkout(self) -> None:
        self.write()
        self.out.mkdir()
        marker = self.out / "owner-file.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(BenchError, "already exists"):
            prepare(self.input, self.out)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        with self.assertRaisesRegex(BenchError, "outside Git"):
            prepare(self.input, Path(__file__).resolve().parents[1] / "bench-output")

    def test_duplicate_json_keys_and_incomplete_inventory_fail_closed(self) -> None:
        self.input.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
        with self.assertRaises(BenchError):
            prepare(self.input, self.out)
        self.data["split_inventory"]["holdout"].pop()
        self.write()
        with self.assertRaises(BenchError):
            prepare(self.input, self.out)

    def test_cli_reads_only_without_model_inference_or_credentials(self) -> None:
        self.write()
        run = subprocess.run([
            sys.executable, "-m", "evaluation.paired_model_bench", "prepare",
            "--bundle", str(self.input), "--output", str(self.out),
        ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
           check=False, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["run_count"], 4)
        self.assertNotIn("Ada stood", run.stdout)


if __name__ == "__main__":
    unittest.main()
