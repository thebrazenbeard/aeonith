"""Offline synthetic-only checks for private human annotation workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evaluation.quality_eval import ANNOTATION_SCHEMA, DIMENSIONS, PAIR_SCHEMA, STUDY_SCHEMA, digest
from evaluation.human_rater_cli import (
    ReviewerSessionError, assemble_study, collect_private_annotation,
    rate_private_pair, read_private_json,
)


def pair_fixture() -> dict:
    return {
        "schema_version": PAIR_SCHEMA,
        "pair_id": "a" * 24,
        "request": {"work": {"text": "PRIVATE SYNTHETIC passage with a silver bell."}, "lenses": ["symbolic"]},
        "A": {"synthesis": "The bell repeats a social obligation."},
        "B": {"synthesis": "The silver bell makes the scene sound cold."},
        "directions": "Score both anonymized critiques independently.",
    }


def rubric(name: str, pair: dict) -> dict:
    return {
        "schema_version": ANNOTATION_SCHEMA,
        "pair_id": pair["pair_id"],
        "reviewer_pseudonym": name,
        "dimensions": {dim: {"A": 2, "B": 1} for dim in DIMENSIONS},
        "preference": "A",
        "rationale": "The better critique justifies more of its reading with the supplied passage.",
    }


class HumanRaterSessionTests(unittest.TestCase):
    def test_private_text_is_never_shown_before_explicit_consent(self):
        shown: list[str] = []
        with self.assertRaises(ReviewerSessionError):
            collect_private_annotation(pair_fixture(), ask=lambda prompt: "NO", emit=shown.append)
        self.assertNotIn("PRIVATE SYNTHETIC", "\n".join(shown))

    def test_completed_typed_rubric_is_bound_to_exact_display(self):
        answers = iter(["I REVIEWED", "reader-1"] + ["2", "1"] * len(DIMENSIONS)
                       + ["A", "This critique ties its narrative interpretation to the specific passage."])
        shown: list[str] = []
        pair = pair_fixture()
        bound = collect_private_annotation(pair, ask=lambda _: next(answers), emit=shown.append)
        self.assertNotIn("PRIVATE SYNTHETIC", "\n".join(shown))
        self.assertNotIn("The silver bell", "\n".join(shown))
        self.assertIn(digest(pair), "\n".join(shown))
        self.assertEqual(bound["display_sha256"], digest(pair))
        self.assertEqual(bound["annotation"]["reviewer_pseudonym"], "reader-1")
        self.assertEqual(bound["annotation"]["preference"], "A")
        self.assertNotIn("base_model", str(shown))

    def test_incomplete_answers_do_not_create_a_private_rubric(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            pair_file = root / "pair.json"
            pair_file.write_text(json.dumps(pair_fixture()), encoding="utf-8")
            pair_file.chmod(0o600)
            target = root / "unwritten.json"
            answers = iter(["I REVIEWED", "reader-one", "9"])
            with self.assertRaises(ReviewerSessionError):
                rate_private_pair(pair_file, target, ask=lambda _: next(answers), emit=lambda _: None)
            self.assertFalse(target.exists())

    def test_noninteractive_cli_refuses_before_reading_a_private_pair(self):
        proc = subprocess.run(
            [sys.executable, "-m", "evaluation.human_rater_cli", "rate",
             "--pair", "/no-such/private-manuscript.json", "--out", "/no-such/rating.json"],
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("non-logged interactive terminal", proc.stderr)
        self.assertNotIn("/no-such", proc.stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_assembled_real_file_is_owner_only_and_unassessed(self):
        from evaluation.quality_eval import bind_annotation_to_display
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            pair = pair_fixture()
            inputs = {
                "pair.json": pair,
                "first.json": bind_annotation_to_display(rubric("rater-one", pair), pair),
                "second.json": bind_annotation_to_display(rubric("rater-two", pair), pair),
            }
            for name, value in inputs.items():
                target = root / name
                target.write_text(json.dumps(value), encoding="utf-8")
                target.chmod(0o600)
            manifest = {"schema_version": "aeonith.human_study_file_manifest.v1",
                        "records": [{"pair_file": str(root / "pair.json"),
                                     "bound_annotation_files": [str(root / "first.json"), str(root / "second.json")]}]}
            mpath = root / "manifest.json"
            mpath.write_text(json.dumps(manifest), encoding="utf-8")
            mpath.chmod(0o600)
            out = root / "study.json"
            result = assemble_study(mpath, out)
            self.assertEqual(result["status"], "OPERATOR_DECLARED_STUDY_ASSEMBLED")
            self.assertEqual(result["semantic_quality"], "UNASSESSED")
            self.assertFalse(result["human_independence_verified"])
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            contents = read_private_json(out)
            self.assertEqual(contents["schema_version"], STUDY_SCHEMA)
            self.assertEqual(len(contents["records"][0]["annotations"]), 2)
            with self.assertRaises(ReviewerSessionError):
                assemble_study(mpath, out)

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_interactive_collection_produces_owner_only_files_and_private_study(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            pair = pair_fixture()
            pair_file = root / "pair.json"
            pair_file.write_text(json.dumps(pair), encoding="utf-8")
            pair_file.chmod(0o600)
            rating_paths = []
            for number in (1, 2):
                output = root / f"rater{number}.json"
                answers = iter(["I REVIEWED", f"real-person-unverified-{number}"]
                               + ["2", "1"] * len(DIMENSIONS)
                               + ["A", "The first critique has more grounded reasoning about the private sample."])
                shown: list[str] = []
                receipt = rate_private_pair(pair_file, output,
                                            ask=lambda _: next(answers), emit=shown.append)
                self.assertEqual(receipt["status"], "OPERATOR_DECLARED_ANNOTATION_SAVED")
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
                self.assertNotIn("PRIVATE SYNTHETIC", "\n".join(shown))
                self.assertNotIn("The silver bell", "\n".join(shown))
                self.assertNotIn("The first critique has", json.dumps(receipt))
                rating_paths.append(str(output))
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "schema_version": "aeonith.human_study_file_manifest.v1",
                "records": [{"pair_file": str(pair_file), "bound_annotation_files": rating_paths}],
            }), encoding="utf-8")
            manifest_path.chmod(0o600)
            study_path = root / "study.json"
            summary = assemble_study(manifest_path, study_path)
            self.assertEqual(summary["total_annotations"], 2)
            self.assertEqual(summary["semantic_quality"], "UNASSESSED")
            self.assertEqual(stat.S_IMODE(study_path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_rejects_symlinked_and_public_input_without_printing_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            target = root / "pair.json"
            target.write_text(json.dumps(pair_fixture()), encoding="utf-8")
            target.chmod(0o644)
            with self.assertRaises(ReviewerSessionError):
                read_private_json(target)
            target.chmod(0o600)
            link = root / "symlink.json"
            link.symlink_to(target)
            with self.assertRaises(ReviewerSessionError):
                read_private_json(link)
            linked_dir = root / "linked"
            linked_dir.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ReviewerSessionError):
                read_private_json(linked_dir / "pair.json")

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_forged_display_binding_and_duplicate_rater_are_rejected_before_output(self):
        from evaluation.quality_eval import bind_annotation_to_display
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            pair = pair_fixture()
            pair_file = root / "pair.json"
            pair_file.write_text(json.dumps(pair), encoding="utf-8")
            pair_file.chmod(0o600)
            annotation = bind_annotation_to_display(rubric("one-rater", pair), pair)
            first = root / "first.json"
            second = root / "second.json"
            for path in (first, second):
                path.write_text(json.dumps(annotation), encoding="utf-8")
                path.chmod(0o600)
            manifest_file = root / "manifest.json"
            manifest = {"schema_version": "aeonith.human_study_file_manifest.v1",
                        "records": [{"pair_file": str(pair_file),
                                     "bound_annotation_files": [str(first), str(second)]}]}
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_file.chmod(0o600)
            out = root / "study.json"
            with self.assertRaises(ReviewerSessionError):
                assemble_study(manifest_file, out)
            self.assertFalse(out.exists())
            modified = dict(annotation)
            modified["display_sha256"] = "f" * 64
            second.write_text(json.dumps(modified), encoding="utf-8")
            with self.assertRaises(ReviewerSessionError):
                assemble_study(manifest_file, out)
            self.assertFalse(out.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            target = root / "malformed.json"
            target.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
            target.chmod(0o600)
            with self.assertRaises(ReviewerSessionError):
                read_private_json(target)

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_manifest_rejects_thousands_of_references_before_file_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            manifest = {
                "schema_version": "aeonith.human_study_file_manifest.v1",
                "records": [{"pair_file": str(root / "nonexistent-pair.json"),
                             "bound_annotation_files": [str(root / "nonexistent-rating.json")] * 40}
                            for _ in range(101)],
            }
            mpath = root / "manifest.json"
            mpath.write_text(json.dumps(manifest), encoding="utf-8")
            mpath.chmod(0o600)
            out = root / "study.json"
            with self.assertRaises(ReviewerSessionError):
                assemble_study(mpath, out)
            self.assertFalse(out.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX private file boundary")
    def test_total_input_bytes_budget_applies_before_reading_next_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            pair = root / "pair.json"
            pair.write_text(json.dumps(pair_fixture()), encoding="utf-8")
            pair.chmod(0o600)
            mpath = root / "manifest.json"
            mpath.write_text(json.dumps({
                "schema_version": "aeonith.human_study_file_manifest.v1",
                "records": [{"pair_file": str(pair), "bound_annotation_files": []}],
            }), encoding="utf-8")
            mpath.chmod(0o600)
            with patch("evaluation.human_rater_cli.MAX_STUDY_INPUT_BYTES", 500):
                with self.assertRaises(ReviewerSessionError):
                    assemble_study(mpath, root / "not-created.json")
            self.assertFalse((root / "not-created.json").exists())

    @unittest.skipUnless(os.name == "posix", "Linux private mount classification")
    def test_wsl_9p_drvfs_mount_is_rejected_even_with_0600_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            pair = root / "pair.json"
            pair.write_text(json.dumps(pair_fixture()), encoding="utf-8")
            pair.chmod(0o600)
            for fstype in ("9p", "drvfs", "cifs", "fuse.sshfs", None):
                with self.subTest(fstype=fstype):
                    with patch("evaluation.human_rater_cli._linux_mount_type", return_value=fstype):
                        with self.assertRaises(ReviewerSessionError):
                            read_private_json(pair)
                        with self.assertRaises(ReviewerSessionError):
                            rate_private_pair(pair, root / "never-written.json",
                                              ask=lambda _: "", emit=lambda _: None)
            self.assertFalse((root / "never-written.json").exists())


if __name__ == "__main__":
    unittest.main()
