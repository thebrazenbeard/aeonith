"""Generated literary candidate is source-only until separately admitted."""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from aeonith.private_output import PrivateOutputError
from training.synthetic_pilot import (
    build_candidate, create_private_candidate, validate_candidate,
)


class SyntheticPilotTests(unittest.TestCase):
    def test_repeatability_with_42_unique_source_disjoint_examples(self) -> None:
        first = build_candidate()
        self.assertEqual(first, build_candidate())
        self.assertEqual(len(first["examples"]), 42)
        report = validate_candidate(first)
        self.assertEqual(report["split_counts"], {"train": 28, "validation": 7, "holdout": 7})
        self.assertEqual(len(report["lenses_by_split"]["train"]), 14)
        self.assertEqual(len({row["id"] for row in first["examples"]}), 42)
        self.assertEqual(len({row["source_id"] for row in first["examples"]}), 42)
        self.assertEqual(report["status"], "review_pending_not_admitted_or_trained")
        self.assertEqual(report["actual_optimizer_steps"], 0)
        self.assertEqual(report["human_editorial_review"], "not_performed")

    def test_provenance_never_impersonates_a_human_or_grants_rights(self) -> None:
        proposal = build_candidate()
        self.assertEqual(proposal["generator_provenance"], {
            "origin": "model_generated_synthetic",
            "generator": "ChatGPT", "third_party_text_used": False,
            "human_authorship_claimed": False, "publication_authorized": False,
        })
        self.assertEqual(proposal["status"], "REVIEW_PENDING_NOT_TRAINABLE")
        self.assertFalse(any("rights_basis" in row or "permission_to_train" in row
                             or "permission_to_publish_adapter" in row
                             or "rights_claimant" in row or "editorial_accepted" in row
                             for row in proposal["examples"]))
        self.assertNotIn("sole_owner_decision", json.dumps(proposal))

    def test_specific_lenses_have_editorial_grounding_beyond_index_assignment(self) -> None:
        """Guard known curriculum mislabels, not a machine judgment of quality."""
        rows = {row["id"]: row for row in build_candidate()["examples"]}
        expected = {
            "synth-lit-train-004": ("historical_cultural", "timekeeping", "labor"),
            "synth-lit-train-006": ("genre_specific", "vignette", "fable"),
            "synth-lit-train-007": ("stylistic", "uppercase", "contrast"),
            "synth-lit-train-012": ("linguistic", "clause", "opposition"),
            "synth-lit-train-013": ("comparative", "competing", "map"),
            "synth-lit-train-020": ("genre_specific", "quest-parable", "ending"),
            "synth-lit-train-026": ("linguistic", "label", "referent"),
            "synth-lit-holdout-004": ("reader_response", "audience", "spectators"),
            "synth-lit-holdout-006": ("comparative", "comparing", "correction"),
        }
        for identifier, (lens, *terms) in expected.items():
            with self.subTest(identifier=identifier):
                row = rows[identifier]
                self.assertEqual(row["lens"], lens)
                analysis = row["target"]["lens_reviews"][0]["analysis"].lower()
                for term in terms:
                    self.assertIn(term, analysis)

    def test_canonical_training_lenses_have_distinct_specific_analyses(self) -> None:
        candidate = build_candidate()
        train = [row for row in candidate["examples"] if row["split"] == "train"]
        self.assertEqual(sorted(Counter(row["lens"] for row in train).values()), [2] * 14)
        analyses = [row["target"]["lens_reviews"][0]["analysis"] for row in candidate["examples"]]
        syntheses = [row["target"]["synthesis"] for row in candidate["examples"]]
        limitations = [row["target"]["lens_reviews"][0]["limitations"][0]
                       for row in candidate["examples"]]
        self.assertEqual(len(set(analyses)), 42)
        self.assertEqual(len(set(synthesis[:42] for synthesis in syntheses)), 42)
        self.assertEqual(len(set(limitations)), 42)

    def test_generator_rejects_forged_quote(self) -> None:
        candidate = deepcopy(build_candidate())
        candidate["examples"][1]["target"]["lens_reviews"][0]["support"][0]["quote"] = "fabricated direct quotation"
        with self.assertRaisesRegex(ValueError, "quote|structural"):
            validate_candidate(candidate)

    def test_generator_rejects_split_reuse_even_under_new_ids(self) -> None:
        candidate = deepcopy(build_candidate())
        reused = next(row for row in candidate["examples"] if row["split"] == "train")
        held = next(row for row in candidate["examples"] if row["split"] == "holdout")
        held["passage"] = reused["passage"]
        held["target"] = deepcopy(reused["target"])
        held["lens"] = reused["lens"]
        with self.assertRaisesRegex(ValueError, "near-duplicate|overlap"):
            validate_candidate(candidate)

    def test_generator_rejects_impersonating_provenance(self) -> None:
        candidate = deepcopy(build_candidate())
        candidate["generator_provenance"]["human_authorship_claimed"] = True
        with self.assertRaisesRegex(ValueError, "provenance"):
            validate_candidate(candidate)

    @unittest.skipUnless(os.name == "posix", "Only descriptor-pinned Linux output is implemented")
    def test_private_export_writes_proposal_and_text_free_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "unadmitted-synthetic"
            receipt = create_private_candidate(target)
            self.assertTrue(target.is_dir())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(sorted(path.name for path in target.iterdir()), [
                "candidates.json", "generation_receipt.json",
            ])
            proposal_file = target / "candidates.json"
            self.assertEqual(stat.S_IMODE(proposal_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((target / "generation_receipt.json").stat().st_mode), 0o600)
            self.assertEqual(json.loads(proposal_file.read_text()), build_candidate())
            self.assertEqual(receipt["candidate_sha256"], hashlib.sha256(proposal_file.read_bytes()).hexdigest())
            self.assertEqual(json.loads((target / "generation_receipt.json").read_text()), receipt)
            self.assertNotIn("unlit lantern", json.dumps(receipt))
            self.assertEqual(receipt["status"], "review_pending_not_admitted_or_trained")
            with self.assertRaises((OSError, PrivateOutputError)):
                create_private_candidate(target)

    def test_qualified_writer_failure_does_not_fallback_to_plain_file(self) -> None:
        with patch("training.synthetic_pilot.create_private_directory",
                   side_effect=PrivateOutputError("host not qualified")):
            with self.assertRaisesRegex(PrivateOutputError, "host not qualified"):
                create_private_candidate("/nonexistent-do-not-create")


if __name__ == "__main__":
    unittest.main()
