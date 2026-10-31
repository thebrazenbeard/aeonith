"""Contract tests for source-preserving excerpt planning without inference."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import subprocess
import sys
import unittest
from pathlib import Path

from aeonith.core import critique
from aeonith.longform import (
    LongformPlanError, build_segment_request, plan_longform,
)


def collected(text, plan):
    return "".join(text[item["start"]:item["end"]] for item in plan["segments"])


class PlanningTests(unittest.TestCase):
    def test_plan_metadata_never_contains_raw_headings(self):
        canary = "SECRET_CANARY_MEDICAL_NOTE_739"
        plan = plan_longform(f"# {canary}\nA paragraph.", max_chunk_chars=40)
        self.assertNotIn(canary, json.dumps(plan))

    def test_non_target_metadata_and_coverage_tampering_rejected(self):
        text = "A" * 100 + "B" * 100
        plan = plan_longform(text, max_chunk_chars=60)
        self.assertGreater(len(plan["segments"]), 1)
        for change in ("coverage", "other_segment", "section_label"):
            with self.subTest(change=change):
                modified = copy.deepcopy(plan)
                if change == "coverage":
                    modified["coverage"] = "WHOLE_BOOK_VERIFIED"
                elif change == "other_segment":
                    modified["segments"][1]["source_sha256"] = "0" * 64
                else:
                    modified["sections"][0]["label"] = "Unverified fictional claim"
                with self.assertRaises(LongformPlanError):
                    build_segment_request(text, modified, 0)

    def test_builder_rechecks_overlarge_source_even_with_forged_hash(self):
        text = "A" * 2_000_001
        plan = {"schema_version": "aeonith.longform_plan.v1",
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "source_chars": len(text), "title": "",
                "max_chunk_chars": 200_000, "max_request_bytes": 1_000_000,
                "segments": [{"start": 0, "end": 200_000}]}
        with self.assertRaises(LongformPlanError):
            build_segment_request(text, plan, 0)

    def test_unicode_chapters_and_duplicate_headings_cover_exact_source(self):
        text = "# Chapter One\nA🌊B\n\n## Echo\nAnother sea.\n\n# Chapter One\nAn ending."
        plan = plan_longform(text, title="Sea", max_chunk_chars=46)
        self.assertEqual(plan["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(plan["source_utf8_bytes"], len(text.encode()))
        self.assertEqual(plan["offset_unit"], "unicode_code_points")
        self.assertEqual(collected(text, plan), text)
        self.assertGreaterEqual(len(plan["sections"]), 3)
        self.assertEqual([x["label"] for x in plan["sections"]][:3],
                         ["Section 1", "Section 2", "Section 3"])
        self.assertNotIn("Chapter One", json.dumps(plan))
        self.assertEqual(plan, plan_longform(text, title="Sea", max_chunk_chars=46))
        for segment in plan["segments"]:
            self.assertEqual(len(text[segment["start"]:segment["end"]]), segment["chars"])
            self.assertLessEqual(segment["chars"], 46)

    def test_plain_chapter_markers_and_opening_material(self):
        text = "Dedication\n\nChapter 1\nA short opening.\n\nChapter 2\nThe end."
        plan = plan_longform(text, max_chunk_chars=64)
        self.assertEqual([x["label"] for x in plan["sections"]],
                         ["Section 1", "Section 2", "Section 3"])
        self.assertEqual(collected(text, plan), text)

    def test_plain_crlf_headings_are_detected_without_normalizing_offsets(self):
        text = "Chapter 1\r\nFirst.\r\nChapter 2\r\nSecond."
        plan = plan_longform(text)
        self.assertEqual(len(plan["sections"]), 2)
        self.assertEqual(collected(text, plan), text)

    def test_bom_is_preserved_as_source_codepoint_by_cli(self):
        text = "\ufeffA manuscript starts after a BOM."
        result = subprocess.run(
            [sys.executable, "-m", "aeonith.longform", "--input", "-"],
            input=text.encode("utf-8"), capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["source_chars"], len(text))
        self.assertEqual(plan["source_sha256"], hashlib.sha256(text.encode()).hexdigest())

    def test_excessive_section_markers_are_bounded(self):
        with self.assertRaises(LongformPlanError):
            plan_longform("# Ch\n" * 520)

    def test_markdown_heading_with_whitespace_prefix_preserves_prefix(self):
        text = "  \n\n# Main\nParagraph here."
        plan = plan_longform(text)
        self.assertEqual(len(plan["sections"]), 1)
        self.assertEqual(plan["sections"][0]["start"], 0)
        self.assertEqual(collected(text, plan), text)

    def test_enormous_paragraph_has_hard_boundaries_no_truncation(self):
        text = "A" * 120_000
        plan = plan_longform(text, max_chunk_chars=3_000)
        self.assertGreater(len(plan["segments"]), 30)
        self.assertTrue(any(x["boundary"] == "hard" for x in plan["segments"]))
        self.assertEqual(collected(text, plan), text)
        self.assertEqual(plan["segments"][-1]["end"], len(text))
        self.assertTrue(all(x["chars"] <= 3_000 for x in plan["segments"]))

    def test_trailing_blank_lines_are_kept_without_whitespace_only_request(self):
        text = "x" * 128 + "\n\n"
        plan = plan_longform(text, max_chunk_chars=128)
        self.assertEqual(collected(text, plan), text)
        self.assertEqual(len(plan["segments"]), 2)
        self.assertTrue(all(text[s["start"]:s["end"]].strip() for s in plan["segments"]))

    def test_request_bytes_account_for_json_escaping_and_utf8(self):
        text = ('"\\🌊\n' * 350) + "Closing."
        plan = plan_longform(text, title="Escapes", max_chunk_chars=600,
                             max_request_bytes=650)
        self.assertEqual(collected(text, plan), text)
        for index, segment in enumerate(plan["segments"]):
            request = build_segment_request(text, plan, index)
            self.assertEqual(request["schema_version"], "aeonith.review.v1")
            self.assertIn("only the", request["context"])
            blob = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
            self.assertEqual(len(blob), segment["request_utf8_bytes"])
            self.assertLessEqual(len(blob), 650)
            self.assertEqual(critique(request)["status"], "provider_unavailable")

    def test_tampered_source_and_segment_fingerprint_rejected(self):
        text = "Chapter One\nMara stood in the rain."
        plan = plan_longform(text)
        with self.assertRaises(LongformPlanError):
            build_segment_request(text + "!", plan, 0)
        mutated = copy.deepcopy(plan)
        mutated["segments"][0]["start"] = 2
        with self.assertRaises(LongformPlanError):
            build_segment_request(text, mutated, 0)
        mutated = copy.deepcopy(plan)
        mutated["segments"][0]["source_sha256"] = "0" * 64
        with self.assertRaises(LongformPlanError):
            build_segment_request(text, mutated, 0)
        mutated = copy.deepcopy(plan)
        mutated["max_request_bytes"] = 5
        with self.assertRaises(LongformPlanError):
            build_segment_request(text, mutated, 0)

    def test_rejects_plan_with_omitted_or_overlapping_segments(self):
        text = "A" * 140
        plan = plan_longform(text, max_chunk_chars=50)
        self.assertEqual(len(plan["segments"]), 3)
        missing = copy.deepcopy(plan)
        missing["segments"].pop()
        with self.assertRaises(LongformPlanError):
            build_segment_request(text, missing, 0)
        overlap = copy.deepcopy(plan)
        overlap["segments"][1]["start"] -= 1
        with self.assertRaises(LongformPlanError):
            build_segment_request(text, overlap, 0)

    def test_reject_invalid_resource_settings_and_unrepresentable_text(self):
        trials = [
            ("", {}), (" ", {}), ("a\x00b", {}), ("x" * 2_000_001, {}),
            ("\ud800", {}), ("abc", {"title": "\ud800"}),
            ("abc", {"max_chunk_chars": True}),
            ("abc", {"max_chunk_chars": 31}), ("abc", {"max_request_bytes": True}),
            ("abc", {"max_request_bytes": 255}),
            ("abc", {"title": "x" * 501}),
        ]
        for text, kwargs in trials:
            with self.subTest(length=len(text), kwargs=kwargs), self.assertRaises(LongformPlanError):
                plan_longform(text, **kwargs)

    def test_fails_closed_on_whitespace_gap_longer_than_segment(self):
        text = "x" * 100 + " " * 300 + "end"
        with self.assertRaises(LongformPlanError):
            plan_longform(text, max_chunk_chars=40)

    def test_rejects_segment_explosion(self):
        text = "x" * (513 * 32)
        with self.assertRaises(LongformPlanError):
            plan_longform(text, max_chunk_chars=32)

    def test_randomized_nonempty_source_exact_coverage(self):
        rng = random.Random(20261031)
        alphabet = "abc🌊\n"
        for _ in range(80):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(100, 400)))
            plan = plan_longform(text, max_chunk_chars=80)
            self.assertEqual(collected(text, plan), text)
            self.assertEqual(sum(x["source_utf8_bytes"] for x in plan["segments"]),
                             len(text.encode("utf-8")))


class CLITests(unittest.TestCase):
    def test_metadata_cli_does_not_print_manuscript_body(self):
        manuscript = "The unnaturally private fish swam into an abyss."
        result = subprocess.run(
            [sys.executable, "-m", "aeonith.longform", "--input", "-", "--title", "Test"],
            input=manuscript.encode(), capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["source_chars"], len(manuscript))
        self.assertNotIn(manuscript, result.stdout.decode())
        self.assertEqual(plan["coverage"], "exact_contiguous_source")

    def test_bad_utf8_returns_error_without_echo(self):
        result = subprocess.run(
            [sys.executable, "-m", "aeonith.longform", "--input", "-"],
            input=b"\xff\xfePRIVATE", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"PRIVATE", result.stderr)
        self.assertFalse(result.stdout)


if __name__ == "__main__":
    unittest.main()
