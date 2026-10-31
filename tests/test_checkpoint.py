"""Checkpoint scope must not leak preceding author text or trust supplied offsets."""
import copy
import hashlib
import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from aeonith.checkpoint import (
    CheckpointError, checkpoint_segment_request, main, plan_after_checkpoint
)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.pre = "SECRET_REVELATION\\nAn author-deleted answer.\\n"
        self.tail = "# Chapter One\nÉcho returned.\n\n# Chapter Two\nA clock turned.\n"
        self.work = self.pre + "[ps]" + self.tail

    def test_metadata_and_segment_exclude_prefix(self):
        plan = plan_after_checkpoint(self.work, max_chunk_chars=100)
        serialized = json.dumps(plan)
        self.assertNotIn("SECRET_REVELATION", serialized)
        self.assertNotIn("An author-deleted answer", serialized)
        self.assertNotIn(self.tail, serialized)
        self.assertEqual(plan["excluded_prefix_chars"], len(self.pre + "[ps]"))
        self.assertEqual(plan["eligible_chars"], len(self.tail))
        self.assertEqual(plan["full_source_sha256"], hashlib.sha256(self.work.encode()).hexdigest())
        pieces = []
        for n in range(len(plan["excerpt_plan"]["segments"])):
            req = checkpoint_segment_request(self.work, plan, n)
            pieces.append(req["work"]["text"])
            self.assertNotIn("SECRET_REVELATION", req["work"]["text"])
            self.assertNotIn("[ps]", req["work"]["text"])
        self.assertEqual("".join(pieces), self.tail)

    def test_absent_or_multiple_boundary_fail_closed(self):
        for candidate in ("A manuscript with none", "[ps]A[ps]B", "Only preface[ps]   "):
            with self.subTest(candidate=candidate):
                with self.assertRaises(CheckpointError):
                    plan_after_checkpoint(candidate)

    def test_unicode_marker_and_exact_offsets(self):
        s = "🔥 Secret before\ndoorway⇢After marker the story continues."
        plan = plan_after_checkpoint(s, marker="⇢")
        self.assertEqual(plan["checkpoint_end"], s.index("⇢") + 1)
        req = checkpoint_segment_request(s, plan, 0, marker="⇢")
        self.assertEqual(req["work"]["text"], "After marker the story continues.")

    def test_source_revision_and_tampered_metadata_are_rejected(self):
        plan = plan_after_checkpoint(self.work)
        for bad in (self.work + "!", self.work.replace("SECRET", "PUBLIC")):
            with self.assertRaises(CheckpointError):
                checkpoint_segment_request(bad, plan, 0)
        modified = copy.deepcopy(plan)
        modified["excerpt_plan"]["segments"][0]["start"] = 1
        with self.assertRaises(CheckpointError):
            checkpoint_segment_request(self.work, modified, 0)
        modified = copy.deepcopy(plan)
        modified["checkpoint_end"] += 1
        with self.assertRaises(CheckpointError):
            checkpoint_segment_request(self.work, modified, 0)

    def test_wrong_marker_or_index_fails_closed(self):
        plan = plan_after_checkpoint(self.work)
        for marker in ("[PS]", "ps", ""):
            with self.assertRaises(CheckpointError):
                checkpoint_segment_request(self.work, plan, 0, marker=marker)
        for index in (True, -1, 9999, "0"):
            with self.assertRaises(CheckpointError):
                checkpoint_segment_request(self.work, plan, index)

    def test_cli_metadata_only_and_failure_stderr(self):
        out = io.StringIO()
        with patch("aeonith.checkpoint._read_utf8", return_value=self.work), redirect_stdout(out):
            self.assertEqual(main(["--input", "ignored"]), 0)
        self.assertNotIn("SECRET_REVELATION", out.getvalue())
        self.assertNotIn("A clock turned", out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["scope"], "after_checkpoint_exclusive")
        err = io.StringIO()
        with patch("aeonith.checkpoint._read_utf8", return_value="no boundary"), redirect_stderr(err):
            self.assertEqual(main(["--input", "ignored"]), 2)
        self.assertNotIn("no boundary", err.getvalue())


if __name__ == "__main__":
    unittest.main()
