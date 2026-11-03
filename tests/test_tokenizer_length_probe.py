"""Offline synthetic Qwen tokenizer qualification probes (no real ML imports)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experimental.tokenizer_length_probe import (
    TokenizerProbeError, candidate_prompt, measure_synthetic_candidate,
    verify_tokenizer_assets, main,
)
from training.synthetic_pilot import build_candidate


class FakeTokenizer:
    def __init__(self, *, prefix=(1, 2, 3), added=(4, 5, 6), invalid=None):
        self.prefix, self.added, self.invalid = prefix, added, invalid
        self.calls = []

    def __len__(self):
        return 256

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt,
                            return_dict=True):
        # Real Transformers 5.20 Qwen tokenizer's default return_dict=True
        # returns a BatchEncoding mapping, even with tokenize=True. Requiring
        # explicit False avoids mistakenly treating dict length as token count.
        self.calls.append((messages, tokenize, add_generation_prompt, return_dict))
        if self.invalid == "exception":
            raise ValueError("private passage in an injected error")
        if len(messages) == 1:
            tokens = list(self.prefix)
        elif self.invalid == "prefix":
            tokens = [99, *self.added]
        elif self.invalid == "bool":
            tokens = [*self.prefix, True]
        elif self.invalid == "negative":
            tokens = [*self.prefix, -1]
        else:
            tokens = [*self.prefix, *self.added]
        if return_dict or self.invalid == "dict_even_when_false":
            return {"input_ids": tokens, "attention_mask": [1] * len(tokens)}
        if self.invalid == "nested_even_when_false":
            return [tokens]
        if self.invalid == "batched_even_when_false":
            return [tokens, tokens]
        return tokens


class CandidateTokenizerTests(unittest.TestCase):
    def test_source_only_probe_42_rows_and_zero_optimizer(self):
        tokenizer = FakeTokenizer()
        result = measure_synthetic_candidate(tokenizer, max_length=128)
        self.assertEqual(result["split_counts"], {"train": 28, "validation": 7, "holdout": 7})
        self.assertEqual(result["candidate_count"], 42)
        self.assertEqual(result["max_total_tokens"], 6)
        self.assertEqual(result["max_prompt_tokens_masked"], 3)
        self.assertEqual(result["min_completion_tokens"], 3)
        self.assertTrue(result["template_prefix_stable_for_all_candidates"])
        self.assertTrue(result["all_loss_masks_prefix_only"])
        self.assertEqual(len(result["per_item_token_lengths"]), 42)
        self.assertEqual(result["per_item_token_lengths"][0], {
            "row_index": 0, "split": "train", "prompt_tokens_masked": 3,
            "completion_tokens_supervised": 3, "total_tokens": 6,
        })
        self.assertEqual(result["actual_optimizer_steps"], 0)
        self.assertFalse(result["corpus_admitted"])
        self.assertFalse(result["model_loaded"])
        self.assertEqual(len(tokenizer.calls), 84)
        self.assertTrue(all(call[3] is False for call in tokenizer.calls))
        self.assertNotIn("The pier keeper", json.dumps(result))
        self.assertNotIn("At supper", json.dumps(result))
        self.assertRegex(result["candidate_sha256"], "^[a-f0-9]{64}$")

    def test_prompt_mirrors_trainer_contract(self):
        row = build_candidate()["examples"][0]
        prompt = candidate_prompt(row)
        self.assertIn("through only the psychological lens", prompt)
        self.assertIn("PASSAGE:\n", prompt)
        self.assertIn(row["passage"], prompt)
        self.assertIn("return ONLY a JSON object", prompt)

    def test_prefix_or_token_errors_refused_without_echoing_text(self):
        for kind in ("prefix", "exception", "bool", "negative",
                     "dict_even_when_false", "nested_even_when_false",
                     "batched_even_when_false"):
            with self.subTest(kind=kind), self.assertRaises(TokenizerProbeError) as context:
                measure_synthetic_candidate(FakeTokenizer(invalid=kind), max_length=128)
            self.assertNotIn("private passage", str(context.exception))

    def test_no_completion_or_over_length_refused(self):
        for added in ((), tuple(range(4, 150))):
            with self.subTest(added_count=len(added)):
                with self.assertRaises(TokenizerProbeError):
                    measure_synthetic_candidate(FakeTokenizer(added=added), max_length=128)

    def test_exact_4096_boundary_passes_and_4097_overflow_fails(self):
        # Three masked prefix tokens + 4093 supervised completion tokens.
        result = measure_synthetic_candidate(FakeTokenizer(added=(4,) * 4093), max_length=4096)
        self.assertEqual(result["max_total_tokens"], 4096)
        self.assertEqual(result["min_completion_tokens"], 4093)
        with self.assertRaises(TokenizerProbeError):
            measure_synthetic_candidate(FakeTokenizer(added=(4,) * 4094), max_length=4096)

    def test_max_length_requires_strict_contract_bound(self):
        for value in (True, 0, 1, 127, 4097, "512"):
            with self.subTest(value=value), self.assertRaises(TokenizerProbeError):
                measure_synthetic_candidate(FakeTokenizer(), max_length=value)

    def test_missing_or_malformed_tokenizer_rejected(self):
        for tokenizer in (object(), FakeTokenizer(prefix=()), FakeTokenizer(prefix=(1, 257))):
            with self.subTest(tokenizer=tokenizer.__class__.__name__), self.assertRaises(TokenizerProbeError):
                measure_synthetic_candidate(tokenizer, max_length=128)

    def test_default_cli_without_execute_never_imports_transformers(self):
        with patch("experimental.tokenizer_length_probe.load_offline_tokenizer", side_effect=AssertionError("loader called")):
            self.assertEqual(main(["--base-dir", "/does-not-exist"]), 2)


class TokenizerFileVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {
            "schema_version": "aeonith.expected_base_files.v1",
            "upstream_model_id": "Qwen/Qwen3.5-0.8B",
            "upstream_revision": "2fc06364715b967f1860aea9cf38778875588b17",
            "files": [],
        }
        for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "merges.txt", "vocab.json"):
            raw = ("fixture-" + name).encode("utf-8")
            (self.root / name).write_bytes(raw)
            self.manifest["files"].append({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})

    def test_exact_files_verification_source_only(self):
        result = verify_tokenizer_assets(self.root, expected_manifest=self.manifest)
        self.assertEqual(result["verified_file_count"], 6)
        self.assertGreater(result["verified_total_bytes"], 20)
        self.assertFalse(result["model_loader_custody_qualified"])

    def test_rejects_changed_bytes_and_link_leaf(self):
        (self.root / "tokenizer.json").write_bytes(b"substituted")
        with self.assertRaises(TokenizerProbeError):
            verify_tokenizer_assets(self.root, expected_manifest=self.manifest)
        (self.root / "tokenizer.json").unlink()
        (self.root / "tokenizer.json").symlink_to(self.root / "config.json")
        with self.assertRaises(TokenizerProbeError):
            verify_tokenizer_assets(self.root, expected_manifest=self.manifest)

    def test_rejects_forged_manifest_and_path(self):
        with self.assertRaises(TokenizerProbeError):
            verify_tokenizer_assets(self.root, expected_manifest={**self.manifest, "upstream_model_id": "other"})
        with self.assertRaises(TokenizerProbeError):
            verify_tokenizer_assets("relative/path", expected_manifest=self.manifest)


if __name__ == "__main__":
    unittest.main()
