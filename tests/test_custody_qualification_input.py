"""Adversarial source-only tests for pinned input -> immutable corpus memory."""
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from training.corpus import SPLITS
from training.custody_qualification_input import PinnedCorpusError, snapshot_pinned_corpus
from training.private_input import PinnedPrivateInput


def row(split):
    return {
        "id": f"syn-{split}-1",
        "prompt": f"Analyze the turning point in an original {split} scene.",
        "completion": f"The fictional {split} character changes after choosing patience.",
        "source_id": f"invented-{split}-source", "rights_basis": "self_authored",
        "permission_to_train": True, "permission_to_publish_adapter": False,
    }


def encode(item):
    return (json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


@unittest.skipUnless(sys.platform == "linux" and os.path.exists("/proc/self/fd"),
                     "requires native Linux private descriptors")
class PinnedCorpusPilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aeonith-pinned-corpus-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / "owner-private"
        self.private.mkdir(mode=0o700)
        self.paths = {}
        self.hashes = {}
        for split in SPLITS:
            payload = encode(row(split))
            path = self.private / f"{split}.jsonl"
            path.write_bytes(payload)
            path.chmod(0o600)
            self.paths[split] = path
            self.hashes[split] = sha256(payload).hexdigest()

    def open_inputs(self, stack):
        return {split: stack.enter_context(PinnedPrivateInput.open(self.paths[split], max_bytes=4096))
                for split in SPLITS}

    def read(self):
        with ExitStack() as stack:
            return snapshot_pinned_corpus(self.open_inputs(stack), self.hashes)

    def test_exact_digest_and_immutable_memory_and_text_free_receipt(self):
        result = self.read()
        self.assertEqual({key: len(result.rows[key]) for key in SPLITS},
                         {key: 1 for key in SPLITS})
        self.assertEqual(result.rows["train"][0]["id"], "syn-train-1")
        with self.assertRaises(TypeError):
            result.rows["train"][0]["prompt"] = "edited"
        with self.assertRaises(TypeError):
            result.rows["train"] = ()
        receipt = result.source_only_receipt()
        self.assertFalse(receipt["optimizer_authorized"])
        self.assertFalse(receipt["model_loader_custody_qualified"])
        self.assertFalse(receipt["rights_and_source_provenance_verified"])
        self.assertNotIn("Analyze", json.dumps(receipt))
        self.assertEqual(set(receipt["split_sha256_operator_supplied"]), set(SPLITS))

    def test_digest_tamper_rejected(self):
        self.hashes["train"] = "0" * 64
        with self.assertRaisesRegex(PinnedCorpusError, "train differs"):
            self.read()

    def test_ancestor_redirection_does_not_replace_pinned_bytes(self):
        with ExitStack() as stack:
            inputs = self.open_inputs(stack)
            moved = self.root / "owner-private-original"
            self.private.rename(moved)
            decoy = self.root / "decoy"
            decoy.mkdir(mode=0o700)
            (decoy / "train.jsonl").write_bytes(encode(row("validation")))
            self.private.symlink_to(decoy, target_is_directory=True)
            self.assertEqual(self.paths["train"].read_bytes(), encode(row("validation")))
            result = snapshot_pinned_corpus(inputs, self.hashes)
            self.assertEqual(result.rows["train"][0]["id"], "syn-train-1")

    def test_modified_open_inode_rejected(self):
        with ExitStack() as stack:
            inputs = self.open_inputs(stack)
            self.paths["train"].write_bytes(encode({**row("train"), "prompt": "Changed"}))
            with self.assertRaisesRegex(PinnedCorpusError, "train descriptor changed"):
                snapshot_pinned_corpus(inputs, self.hashes)

    def test_alias_inode_rejected(self):
        with ExitStack() as stack:
            inputs = self.open_inputs(stack)
            inputs["validation"] = inputs["train"]
            with self.assertRaisesRegex(PinnedCorpusError, "alias one filesystem inode"):
                snapshot_pinned_corpus(inputs, self.hashes)

    def test_cross_split_source_leakage_rejected(self):
        payload = encode({**row("validation"), "source_id": row("train")["source_id"]})
        self.paths["validation"].write_bytes(payload)
        self.hashes["validation"] = sha256(payload).hexdigest()
        with self.assertRaisesRegex(PinnedCorpusError, "crosses corpus splits"):
            self.read()

    def test_duplicate_json_keys_rejected_even_when_digest_matches(self):
        raw = encode(row("train")).rstrip(b"\n").rstrip(b"}") + b',"id":"a-second-id"}\n'
        self.paths["train"].write_bytes(raw)
        self.hashes["train"] = sha256(raw).hexdigest()
        with self.assertRaisesRegex(PinnedCorpusError, "row 1 is invalid"):
            self.read()

    def test_invalid_digest_or_incomplete_splits_rejected(self):
        with ExitStack() as stack:
            inputs = self.open_inputs(stack)
            with self.assertRaisesRegex(PinnedCorpusError, "digest keys"):
                snapshot_pinned_corpus(inputs, {"train": self.hashes["train"]})
            with self.assertRaisesRegex(PinnedCorpusError, "invalid expected split digest"):
                snapshot_pinned_corpus(inputs, {**self.hashes, "train": "pending"})
            with self.assertRaisesRegex(PinnedCorpusError, "descriptor and digest keys"):
                snapshot_pinned_corpus({"train": inputs["train"]}, self.hashes)

    def test_closed_descriptor_rejected(self):
        with ExitStack() as stack:
            inputs = self.open_inputs(stack)
            inputs["train"].close()
            with self.assertRaisesRegex(PinnedCorpusError, "train descriptor changed"):
                snapshot_pinned_corpus(inputs, self.hashes)

    def test_oversized_pinned_file_rejected_before_private_read_allocation(self):
        self.paths["train"].write_bytes(b"x" * (4 * 1024 * 1024 + 1))
        with ExitStack() as stack:
            inputs = {
                split: stack.enter_context(PinnedPrivateInput.open(self.paths[split],
                           max_bytes=8 * 1024 * 1024))
                for split in SPLITS
            }
            with patch.object(inputs["train"], "read_bytes", side_effect=AssertionError("should not read")):
                with self.assertRaisesRegex(PinnedCorpusError, "input byte budget"):
                    snapshot_pinned_corpus(inputs, self.hashes)


if __name__ == "__main__":
    unittest.main()
