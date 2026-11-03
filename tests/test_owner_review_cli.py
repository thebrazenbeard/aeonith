"""Owner review is an explicit interactive step, not an automatic grant."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_synthetic_generated_admission import candidate_example


class PrivateTerminal:
    def __init__(self, answers: list[str]):
        self.answers = iter(answers)
        self.output = io.StringIO()

    def write(self, value: str) -> int:
        return self.output.write(value)

    def flush(self) -> None:
        pass

    def readline(self) -> str:
        answer = next(self.answers, None)
        return "" if answer is None else answer + "\n"


class OwnerReviewCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.candidate_path = root / "candidates.json"
        self.output_path = root / "approval-new"
        self.candidate = {
            "schema_version": "aeonith.candidate_corpus.v1",
            "status": "REVIEW_PENDING_NOT_TRAINABLE",
            "generator_provenance": {
                "origin": "model_generated_synthetic", "generator": "ChatGPT",
                "third_party_text_used": False, "human_authorship_claimed": False,
                "publication_authorized": False,
            },
            "examples": [candidate_example(1, "train"),
                         candidate_example(2, "validation"),
                         candidate_example(3, "holdout")],
        }
        self.candidate_path.write_text(json.dumps(self.candidate), encoding="utf-8")
        self.candidate_path.chmod(0o600)
        self.digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()

    def test_review_requires_all_choices_and_exact_final_confirmation(self):
        from training.review_candidates import review_candidates

        terminal = PrivateTerminal(["admit", "admit", "admit", "Patrick Sims",
                                    self.digest, "APPROVE_PRIVATE_LOCAL_TRAINING"])
        ordinary_stdout = io.StringIO()
        with redirect_stdout(ordinary_stdout):
            receipt = review_candidates(self.candidate_path, self.output_path, terminal)
        self.assertEqual(ordinary_stdout.getvalue(), "")
        self.assertEqual(receipt["candidate_sha256"], self.digest)
        self.assertTrue((self.output_path / "approval.json").is_file())
        approval = json.loads((self.output_path / "approval.json").read_text(encoding="utf-8"))
        self.assertEqual(approval["schema_version"], "aeonith.candidate_synthetic_admission.v2")
        self.assertTrue(all(item["disposition"] == "admit" for item in approval["records"]))
        self.assertFalse(any(item["permission_to_publish_adapter"] for item in approval["records"]))
        self.assertIn(self.candidate["examples"][0]["passage"], terminal.output.getvalue())

    def test_aborted_review_cannot_create_approval(self):
        from training.review_candidates import review_candidates, ReviewAborted

        terminal = PrivateTerminal(["admit", "quit"])
        with self.assertRaises(ReviewAborted):
            review_candidates(self.candidate_path, self.output_path, terminal)
        self.assertFalse(self.output_path.exists())

    def test_wrong_final_hash_cannot_create_approval(self):
        from training.review_candidates import review_candidates, ReviewAborted

        terminal = PrivateTerminal(["admit", "admit", "admit", "Patrick Sims",
                                    "0" * 64, "APPROVE_PRIVATE_LOCAL_TRAINING"])
        with self.assertRaises(ReviewAborted):
            review_candidates(self.candidate_path, self.output_path, terminal)
        self.assertFalse(self.output_path.exists())

    def test_early_eof_or_keyboard_interrupt_leaves_no_approval(self):
        from training.review_candidates import review_candidates, ReviewAborted

        with self.assertRaises(ReviewAborted):
            review_candidates(self.candidate_path, self.output_path,
                              PrivateTerminal(["admit"]))
        self.assertFalse(self.output_path.exists())

        class InterruptedTerminal(PrivateTerminal):
            def readline(self):
                self.count = getattr(self, "count", 0) + 1
                if self.count == 2:
                    raise KeyboardInterrupt
                return super().readline()

        with self.assertRaises(KeyboardInterrupt):
            review_candidates(self.candidate_path, self.output_path,
                              InterruptedTerminal(["admit", "admit"]))
        self.assertFalse(self.output_path.exists())

    def test_unqualified_private_file_or_windows_refused_before_any_output(self):
        from training.review_candidates import review_candidates, ReviewAborted

        self.candidate_path.chmod(0o644)
        with self.assertRaises(ReviewAborted):
            review_candidates(self.candidate_path, self.output_path,
                              PrivateTerminal(["admit"] * 3))
        self.assertFalse(self.output_path.exists())
        self.candidate_path.chmod(0o600)

        with patch("training.review_candidates.sys.platform", "win32"):
            with self.assertRaises(ReviewAborted):
                review_candidates(self.candidate_path, self.output_path,
                                  PrivateTerminal(["admit"] * 3))
        self.assertFalse(self.output_path.exists())

        linked_path = self.candidate_path.parent / "linked.json"
        os.link(self.candidate_path, linked_path)
        with self.assertRaises(ReviewAborted):
            review_candidates(self.candidate_path, self.output_path,
                              PrivateTerminal(["admit"] * 3))
        self.assertFalse(self.output_path.exists())

    def test_candidate_leaf_mount_must_be_independently_qualified(self):
        from aeonith.private_output import PrivateOutputError
        from training.review_candidates import review_candidates, ReviewAborted

        # A bind-mounted file may be on a different filesystem from its
        # otherwise qualified parent directory. Check the opened leaf FD.
        with patch("training.review_candidates._require_local_posix_mount",
                   side_effect=PrivateOutputError("unqualified leaf mount")):
            with self.assertRaises(ReviewAborted):
                review_candidates(self.candidate_path, self.output_path,
                                  PrivateTerminal(["admit", "admit", "admit", "Patrick Sims",
                                                   self.digest, "APPROVE_PRIVATE_LOCAL_TRAINING"]))
        self.assertFalse(self.output_path.exists())

    @unittest.skipUnless(sys.platform == "linux", "FIFO race is a Linux open() contract")
    def test_candidate_swap_to_fifo_fails_without_blocking(self):
        # The lexical candidate-path check sees a regular file. An attacker
        # then substitutes a FIFO just before openat(). O_NOFOLLOW alone does
        # not keep a blocking FIFO open from hanging forever.
        script = r'''
import os, sys
from pathlib import Path
from unittest.mock import patch
from training import review_candidates as subject
candidate = Path(sys.argv[1]); destination = Path(sys.argv[2])
real_parent = subject._open_parent_fd
calls = 0
def replace_then_open(path):
    global calls
    calls += 1
    if calls == 2:
        candidate.unlink()
        os.mkfifo(candidate, 0o600)
    return real_parent(path)
with patch.object(subject, "_open_parent_fd", side_effect=replace_then_open):
    try:
        subject.review_candidates(candidate, destination, object())
    except subject.ReviewAborted:
        sys.exit(0)
sys.exit(1)
'''
        proc = subprocess.run([sys.executable, "-c", script, str(self.candidate_path),
                               str(self.output_path)], capture_output=True, text=True,
                              timeout=2, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[:500])
        self.assertFalse(self.output_path.exists())

    def test_mutating_candidate_during_interactive_review_refuses_approval(self):
        from training.review_candidates import review_candidates, ReviewAborted

        class EditingTerminal(PrivateTerminal):
            def readline(self):
                self.count = getattr(self, "count", 0) + 1
                if self.count == 5:
                    self_path.write_text("{}", encoding="utf-8")
                return super().readline()

        self_path = self.candidate_path
        terminal = EditingTerminal(["admit", "admit", "admit", "Patrick Sims",
                                    self.digest, "APPROVE_PRIVATE_LOCAL_TRAINING"])
        with self.assertRaises(ReviewAborted):
            review_candidates(self.candidate_path, self.output_path, terminal)
        self.assertFalse(self.output_path.exists())

    def test_rejected_record_is_explicit_denial_with_reason_and_no_text_in_approval(self):
        from training.review_candidates import review_candidates

        self.candidate["examples"].append(candidate_example(4, "train"))
        self.candidate_path.write_text(json.dumps(self.candidate), encoding="utf-8")
        self.candidate_path.chmod(0o600)
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        terminal = PrivateTerminal(["reject", "quality", "admit", "admit", "admit",
                                    "Patrick Sims", digest, "APPROVE_PRIVATE_LOCAL_TRAINING"])
        receipt = review_candidates(self.candidate_path, self.output_path, terminal)
        self.assertEqual(receipt["record_disposition_counts"], {"reject": 1, "admit": 3})
        text = (self.output_path / "approval.json").read_text(encoding="utf-8")
        approval = json.loads(text)
        self.assertEqual(approval["records"][0]["disposition"], "reject")
        self.assertFalse(approval["records"][0]["permission_to_train"])
        self.assertEqual(approval["records"][0]["reason_code"], "quality")
        self.assertNotIn("At hour 1, Nira", text)

    def test_review_displays_untrusted_text_without_terminal_controls_or_bidi_spoofing(self):
        from training.review_candidates import review_candidates

        injection = "\x1b[2J\x1b]52;c;ZGF0YQ==\x07\u202eFORGED DECISION\u202c"
        self.candidate["examples"][0]["passage"] += injection
        self.candidate["examples"][0]["target"]["lens_reviews"][0]["analysis"] += "\u202eFALSE REVIEW\u202c"
        self.candidate_path.write_text(json.dumps(self.candidate), encoding="utf-8")
        self.candidate_path.chmod(0o600)
        digest = hashlib.sha256(self.candidate_path.read_bytes()).hexdigest()
        tty = PrivateTerminal(["admit", "admit", "admit", "Patrick Sims",
                               digest, "APPROVE_PRIVATE_LOCAL_TRAINING"])
        review_candidates(self.candidate_path, self.output_path, tty)
        displayed = tty.output.getvalue()
        self.assertNotIn("\x1b", displayed)
        self.assertNotIn("\x07", displayed)
        self.assertNotIn("\u202e", displayed)
        self.assertNotIn("\u202c", displayed)
        self.assertIn("\\u001b[2J", displayed)
        self.assertIn("\\u202eFORGED DECISION", displayed)
        self.assertIn("\\u202eFALSE REVIEW", displayed)
        self.assertIn("copper bell", displayed)


if __name__ == "__main__":
    unittest.main()
