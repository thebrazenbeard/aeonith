"""Offline schema-reference sanity checks without a third-party validator."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "evaluation"


class SchemaReferenceTests(unittest.TestCase):
    def test_human_study_schemas_have_only_resolvable_local_references(self):
        for filename in ("human_study_bundle.schema.json", "study_annotation.schema.json"):
            with self.subTest(filename=filename):
                document = json.loads((ROOT / filename).read_text(encoding="utf-8"))

                def traverse(node):
                    if isinstance(node, dict):
                        ref = node.get("$ref")
                        if ref is not None:
                            self.assertTrue(ref.startswith("#/"),
                                            f"remote schema reference in {filename}: {ref}")
                            target = document
                            for segment in ref[2:].split("/"):
                                target = target[segment.replace("~1", "/").replace("~0", "~")]
                            self.assertIsInstance(target, dict)
                        for value in node.values():
                            traverse(value)
                    elif isinstance(node, list):
                        for value in node:
                            traverse(value)

                traverse(document)


if __name__ == "__main__":
    unittest.main()
