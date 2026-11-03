"""Source-only contract for the pinned public Qwen3.5-0.8B expectation."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from training.verify_base import _expected_files


class OfficialManifestTests(unittest.TestCase):
    def test_manifest_schema_and_known_lfs_anchors(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / "training" / "manifests" / "qwen3.5-0.8b-2fc06364715b967f1860aea9cf38778875588b17.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        model, revision, files = _expected_files(document)
        self.assertEqual(model, "Qwen/Qwen3.5-0.8B")
        self.assertEqual(revision, "2fc06364715b967f1860aea9cf38778875588b17")
        self.assertEqual(len(files), 10)
        self.assertEqual(sum(entry["bytes"] for entry in files.values()), 1769905646)
        self.assertEqual(files["model.safetensors-00001-of-00001.safetensors"], {
            "bytes": 1746942600,
            "sha256": "04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696",
        })
        self.assertEqual(files["tokenizer.json"]["sha256"],
                         "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42")


if __name__ == "__main__":
    unittest.main()
