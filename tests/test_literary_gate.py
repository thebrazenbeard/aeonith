"""End-to-end offline regression tests; fake injected providers make no model calls."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from aeonith.core import critique
from evaluation.literary_gate import (
    _private_output_path, _request, account, load_cases, load_journal, make_packets,
    make_plan, run_candidate,
)
from evaluation.quality_eval import audit_review


class FakeProvider:
    name = "fake-local-provider"

    def __init__(self, *, fail_on: set[int] | None = None, spoofed: bool = False):
        self.calls = 0
        self.fail_on = fail_on or set()
        self.spoofed = spoofed

    def review(self, payload):
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("synthetic provider failure")
        text = payload["task"]["work"]["text"]
        return {
            "lens_reviews": [{
                "lens": "symbolic", "basis": "textual",
                "analysis": f"The supplied sentence permits a cautious reading. {text[:60]}",
                "support": [{"source": "work", "quote": text[: min(20, len(text))]}],
                "limitations": ["No wider work or author intention is available."],
            }],
            "synthesis": "The possible symbol remains contingent on local textual evidence.",
            "challenges": [], "uncertainties": [], "assessment": None,
            "provider_name": "SECRET_DO_NOT_BLIND" if self.spoofed else "fake",
        }


class LiteraryGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = make_plan(["candidate-B", "candidate-A"], "screen")

    def journal(self, candidate: str, *, provider=None, model=None, artifact_file=None):
        path = self.root / f"{candidate}.jsonl"
        fake = provider or FakeProvider()
        run_candidate(self.plan, candidate, provider=fake,
                      model=model if model is not None else f"fake-{candidate}",
                      lane="production", journal_path=str(path),
                      artifact_file=str(artifact_file) if artifact_file else None)
        return path, fake

    def test_frozen_stimuli_match_written_literary_gate_and_full_denominators(self):
        cases = load_cases()
        self.assertEqual(len(cases), 18)
        self.assertEqual(cases[0]["text"], "At dusk the bell rang once. Mara looked toward the harbor.")
        self.assertEqual(cases[-1]["title"], "Dialogue subtext")
        self.assertEqual(len(self.plan["attempts"]), 12)
        full = make_plan(["candidate-A", "candidate-B"], "full")
        self.assertEqual(len(full["attempts"]), 108)
        self.assertEqual(full["repeats_per_case"], 3)
        self.assertEqual(full["case_set_sha256"], self.plan["case_set_sha256"])

    def test_journals_include_all_failures_not_just_successes(self):
        a, _ = self.journal("candidate-A", provider=FakeProvider(fail_on={2, 6}))
        b, _ = self.journal("candidate-B")
        header, rows = load_journal(str(a), self.plan)
        self.assertEqual(header["host_preflight"], "OPERATOR_ATTESTED_NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(len(rows), 6)
        result, _ = account(self.plan, str(a), str(b))
        self.assertEqual(result["attempts_expected"], 12)
        self.assertEqual(result["candidates"]["candidate-A"]["provider_noncompletion"], 2)
        self.assertEqual(result["candidates"]["candidate-B"]["structural_pass"], 6)
        self.assertEqual(result["blinded_pairs_eligible"], 4)
        self.assertEqual(result["blinded_pairs_total"], 6)
        self.assertEqual(result["semantic_quality"], "UNASSESSED")
        self.assertEqual(result["model_identity_status"],
                         "DIFFERENT_DECLARED_LABELS_ONLY_RUNTIME_UNVERIFIED")
        self.assertFalse(result["independent_model_comparison_eligible"])
        if os.name == "posix":
            self.assertEqual(a.stat().st_mode & 0o777, 0o600)

    def test_crash_during_inference_is_interrupted_not_never_attempted(self):
        a, _ = self.journal("candidate-A")
        b, _ = self.journal("candidate-B")
        truncated_lines = b.read_text(encoding="utf-8").splitlines(keepends=True)[:-1]
        b.write_text("".join(truncated_lines), encoding="utf-8")
        result, _ = account(self.plan, str(a), str(b))
        self.assertEqual(result["candidates"]["candidate-B"]["interrupted"], 1)
        self.assertEqual(result["candidates"]["candidate-B"]["not_attempted"], 0)
        self.assertEqual(result["blinded_pairs_eligible"], 5)

        # A process killed before its next start event instead leaves a truly
        # unattempted slot. The denominator must include that too.
        b.write_text("".join(truncated_lines[:-1]), encoding="utf-8")
        result, _ = account(self.plan, str(a), str(b))
        self.assertEqual(result["candidates"]["candidate-B"]["not_attempted"], 1)
        self.assertEqual(result["candidates"]["candidate-B"]["interrupted"], 0)

    def test_truncated_tail_is_conservatively_counted_and_duplicate_jsonl_rejected(self):
        a, _ = self.journal("candidate-A")
        b, _ = self.journal("candidate-B")
        a.write_bytes(a.read_bytes()[:-1])
        result, _ = account(self.plan, str(a), str(b))
        self.assertEqual(result["journals_with_discarded_incomplete_tails"], 1)
        self.assertEqual(result["candidates"]["candidate-A"]["interrupted"], 1)
        self.assertEqual(result["candidates"]["candidate-A"]["denominator"], 6)
        self.assertEqual(result["blinded_pairs_eligible"], 5)
        with self.assertRaisesRegex(ValueError, "blind review is blocked"):
            make_packets(self.plan, str(a), str(b), seed="not-for-annotation")
        # Force the Windows CRLF failure mode on every platform: text-mode
        # newline normalization must not turn a terminal CR into an LF.
        a.write_bytes(a.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        result, _ = account(self.plan, str(a), str(b))
        self.assertEqual(result["journals_with_discarded_incomplete_tails"], 1)
        self.assertEqual(result["candidates"]["candidate-A"]["interrupted"], 1)
        a, _ = self._replace_journal("candidate-A", a)
        rows = a.read_text(encoding="utf-8").splitlines(keepends=True)
        a.write_text("".join(rows + [rows[1]]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate attempt"):
            account(self.plan, str(a), str(b))

    def test_private_outputs_cannot_land_in_git_checkout_or_symlink_to_it(self):
        repo = Path(__file__).resolve().parents[1]
        forbidden = repo / "never-create-literary-journal-test.jsonl"
        with self.assertRaisesRegex(ValueError, "outside Git checkouts"):
            _private_output_path(str(forbidden))
        self.assertFalse(forbidden.exists())
        with self.assertRaisesRegex(ValueError, "outside Git checkouts"):
            run_candidate(self.plan, "candidate-A", provider=FakeProvider(),
                          model="fake", lane="production", journal_path=str(forbidden))
        self.assertFalse(forbidden.exists())
        alias = self.root / "repo-alias"
        try:
            alias.symlink_to(repo, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass  # Windows can restrict symlink creation without developer mode.
        else:
            with self.assertRaisesRegex(ValueError, "outside Git checkouts"):
                _private_output_path(str(alias / "never-create.jsonl"))

        unrelated_checkout = self.root / "a-different-repository"
        (unrelated_checkout / ".git").mkdir(parents=True)
        (unrelated_checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaisesRegex(ValueError, "outside Git checkouts"):
            _private_output_path(str(unrelated_checkout / "private-journal.jsonl"))
        self.assertFalse((unrelated_checkout / "private-journal.jsonl").exists())

    def test_identity_preflight_refuses_same_label_or_same_local_bytes(self):
        a, _ = self.journal("candidate-A", model="same-model-label")
        b, _ = self.journal("candidate-B", model="same-model-label")
        with self.assertRaisesRegex(ValueError, "same declared model label"):
            account(self.plan, str(a), str(b))
        with self.assertRaisesRegex(ValueError, "same declared model label"):
            make_packets(self.plan, str(a), str(b), seed="test")

        a.unlink()
        b.unlink()
        file_one = self.root / "first-weights.gguf"
        file_two = self.root / "different-name-same-weights.gguf"
        file_one.write_bytes(b"synthetic identical weights")
        file_two.write_bytes(file_one.read_bytes())
        a, _ = self.journal("candidate-A", model="different-a", artifact_file=file_one)
        b, _ = self.journal("candidate-B", model="different-b", artifact_file=file_two)
        header, _ = load_journal(str(a), self.plan)
        self.assertEqual(header["local_artifact_sha256"],
                         hashlib.sha256(file_one.read_bytes()).hexdigest())
        self.assertNotIn(str(file_one), a.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "same local model-artifact digest"):
            account(self.plan, str(a), str(b))

    def test_distinct_local_bytes_still_cannot_prove_provider_binding(self):
        one = self.root / "base.gguf"
        two = self.root / "adapter.gguf"
        one.write_bytes(b"first synthetic artifact")
        two.write_bytes(b"second synthetic artifact")
        a, _ = self.journal("candidate-A", model="local", artifact_file=one)
        b, _ = self.journal("candidate-B", model="local", artifact_file=two)
        accounting, _ = account(self.plan, str(a), str(b))
        self.assertEqual(accounting["model_identity_status"],
                         "DISTINCT_LOCAL_FILE_HASHES_RUNTIME_UNVERIFIED")
        self.assertFalse(accounting["independent_model_comparison_eligible"])
        self.assertEqual(accounting["blinded_pairs_eligible"], 6)

    def test_artifact_rejects_empty_and_symlink_without_creating_journal(self):
        empty = self.root / "empty.gguf"
        empty.touch()
        target = self.root / "candidate-A.jsonl"
        fake = FakeProvider()
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            run_candidate(self.plan, "candidate-A", provider=fake, model="x",
                          lane="production", journal_path=str(target),
                          artifact_file=str(empty))
        self.assertFalse(target.exists())
        self.assertEqual(fake.calls, 0)

    def _replace_journal(self, candidate, old_path):
        old_path.unlink()
        return self.journal(candidate)

    def test_blinded_packets_contain_no_candidate_or_provider_identity(self):
        a, _ = self.journal("candidate-A", provider=FakeProvider(spoofed=True))
        b, _ = self.journal("candidate-B")
        displays, keys, accounting = make_packets(self.plan, str(a), str(b), seed="sealed-001")
        self.assertEqual(len(displays["pairs"]), accounting["blinded_pairs_eligible"])
        serialized = json.dumps(displays)
        self.assertNotIn("candidate-A", serialized)
        self.assertNotIn("candidate-B", serialized)
        self.assertNotIn("SECRET_DO_NOT_BLIND", serialized)
        self.assertIn("candidate-A", json.dumps(keys))
        self.assertEqual(displays["pairs"][0]["case_id"], "R01-N")
        # All fake runs return identical prose per case across repeats, yet
        # each occurrence must be annotatable in the aggregator separately.
        pair_ids = [row["pair"]["pair_id"] for row in displays["pairs"]]
        self.assertEqual(len(pair_ids), len(set(pair_ids)))
        self.assertEqual([row["pair"]["pair_id"] for row in displays["pairs"]],
                         [row["key"]["pair_id"] for row in keys["keys"]])

    def test_source_anchor_pass_does_not_verify_quotes_in_free_form_analysis(self):
        class InventedProseQuote(FakeProvider):
            def review(self, payload):
                candidate = super().review(payload)
                candidate["lens_reviews"][0]["analysis"] = (
                    'The passage says "The bell rang ten times" in Chapter Twelve.'
                )
                return candidate

        request = _request(load_cases()[0])
        self.assertNotIn("The bell rang ten times", request["work"]["text"])
        review = critique(request, InventedProseQuote())
        self.assertEqual(review["status"], "completed")
        audit = audit_review(request, review)
        # This is deliberately a structural pass, NOT a literary/quote-integrity
        # success: only explicit support anchors are checked for source match.
        self.assertEqual(audit["structural_status"], "pass")
        self.assertEqual(audit["semantic_quality"], "UNASSESSED")

    def test_cross_candidate_and_lane_journals_refused(self):
        a, _ = self.journal("candidate-A")
        with self.assertRaisesRegex(ValueError, "distinct candidates"):
            account(self.plan, str(a), str(a))

    def test_rejects_overwrite_before_any_provider_call(self):
        path = self.root / "candidate-A.jsonl"
        path.write_text("existing user data", encoding="utf-8")
        provider = FakeProvider()
        with self.assertRaises(FileExistsError):
            run_candidate(self.plan, "candidate-A", provider=provider,
                          model="fake", lane="production", journal_path=str(path))
        self.assertEqual(provider.calls, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "existing user data")

    def test_cli_remote_url_is_refused_without_creating_journal(self):
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        output = self.root / "journal.jsonl"
        result = subprocess.run([
            sys.executable, "-m", "evaluation.literary_gate", "run",
            "--plan", str(plan_path), "--candidate", "candidate-A", "--model", "fake",
            "--url", "https://example.com/v1/chat/completions", "--host-qualified",
            "--lane", "production", "--out", str(output),
        ], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
