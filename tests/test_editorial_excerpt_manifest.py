"""Pure, synthetic falsifiers for a private source-bound excerpt manifest."""

import hashlib
import re
import unittest
from unittest.mock import patch

from aeonith.editorial_excerpt_manifest import (
    ExcerptManifestError,
    SourceRecord,
    prepare_excerpt_manifest,
)


def _record(text, source_id="work.canto-001", revision_id="draft.7"):
    return SourceRecord(source_id, revision_id, hashlib.sha256(text.encode("utf-8")).hexdigest())


class ExcerptManifestTests(unittest.TestCase):
    def test_unicode_codepoint_offsets_and_lossless_coverage(self):
        text = "Rain 🌧️ fell.\n\nÉlan and a snowman ☃ returned."
        source = _record(text)
        result = prepare_excerpt_manifest(source, source, text, max_excerpt_chars=16)
        self.assertEqual(result.offset_unit, "unicode_code_points")
        self.assertEqual(result.source_chars, len(text))
        self.assertEqual(result.coverage, "EXACT_CONTIGUOUS")
        self.assertEqual(result.gaps, ())
        self.assertEqual("".join(part.text for part in result.excerpts), text)
        self.assertEqual(result.excerpts[0].start, 0)
        self.assertEqual(result.excerpts[-1].end, len(text))
        self.assertTrue(all(0 < len(part.text) <= 16 for part in result.excerpts))
        for item in result.excerpts:
            self.assertEqual(text[item.start:item.end], item.text)
            self.assertEqual(item.source_id, source.source_id)
            self.assertEqual(item.revision_id, source.revision_id)
            self.assertEqual(item.source_sha256, source.source_sha256)
        self.assertEqual(result.report()["semantic_quality"], "UNASSESSED")

    def test_stale_source_digest_rejected(self):
        original = "She walked toward the shore."
        selected = _record(original)
        with self.assertRaisesRegex(ExcerptManifestError, "^SOURCE_HASH_MISMATCH$"):
            prepare_excerpt_manifest(selected, selected, original + " Again.")

    def test_forged_submission_identity_or_revision_rejected(self):
        text = "The road bent beneath the stars."
        selected = _record(text)
        for submitted in (
            _record(text, source_id="work.canto-002"),
            _record(text, revision_id="draft.8"),
            SourceRecord(selected.source_id, selected.revision_id, "0" * 64),
        ):
            with self.subTest(submitted=submitted):
                with self.assertRaisesRegex(ExcerptManifestError, "^SELECTION_MISMATCH$"):
                    prepare_excerpt_manifest(selected, submitted, text)

    def test_forged_matching_submission_cannot_override_trusted_selection(self):
        selected = _record("Original text.")
        forged = _record("Forged text.")
        with self.assertRaisesRegex(ExcerptManifestError, "^SELECTION_MISMATCH$"):
            prepare_excerpt_manifest(selected, forged, "Forged text.")

    def test_repeated_phrases_retain_distinct_absolute_offsets(self):
        text = "again again again again"
        source = _record(text)
        result = prepare_excerpt_manifest(source, source, text, max_excerpt_chars=7)
        self.assertEqual("".join(p.text for p in result.excerpts), text)
        self.assertEqual([(p.start, p.end) for p in result.excerpts], [(0, 7), (7, 14), (14, 21), (21, 23)])

    def test_paragraph_preference_without_omitting_whitespace(self):
        text = "first paragraph\n\nsecond paragraph\n\nthird paragraph"
        source = _record(text)
        result = prepare_excerpt_manifest(source, source, text, max_excerpt_chars=32)
        self.assertEqual(result.excerpts[0].text, "first paragraph\n\n")
        self.assertEqual(result.excerpts[0].boundary, "paragraph")
        self.assertEqual("".join(p.text for p in result.excerpts), text)

    def test_unreviewable_all_whitespace_middle_segment_fails_without_dropping_it(self):
        text = "Start" + (" " * 50) + "Finish"
        source = _record(text)
        with self.assertRaisesRegex(ExcerptManifestError, "^UNREVIEWABLE_EXCERPT$"):
            prepare_excerpt_manifest(source, source, text, max_excerpt_chars=10)

    def test_maximum_exact_12000_and_12001_split_without_loss(self):
        for chars, expected_parts in ((12_000, 1), (12_001, 2)):
            with self.subTest(chars=chars):
                text = "a" * chars
                record = _record(text)
                result = prepare_excerpt_manifest(record, record, text)
                self.assertEqual(len(result.excerpts), expected_parts)
                self.assertEqual("".join(p.text for p in result.excerpts), text)
                self.assertTrue(all(len(p.text) <= 12_000 for p in result.excerpts))

    def test_invalid_limits_and_excessive_part_count_reject_without_truncation(self):
        text = "a" * 500
        source = _record(text)
        for bound in (True, 0, -1, 12_001, "12000"):
            with self.subTest(bound=bound):
                with self.assertRaisesRegex(ExcerptManifestError, "^INVALID_LIMIT$"):
                    prepare_excerpt_manifest(source, source, text, max_excerpt_chars=bound)
        with self.assertRaisesRegex(ExcerptManifestError, "^TOO_MANY_EXCERPTS$"):
            prepare_excerpt_manifest(source, source, text, max_excerpt_chars=1)

    def test_oversized_character_or_utf8_byte_source_rejected(self):
        for text in ("a" * 1_000_001, "🌊" * 1_000_000):
            with self.subTest(chars=len(text)):
                source = _record(text)
                with self.assertRaisesRegex(ExcerptManifestError, "^SOURCE_TOO_LARGE$"):
                    prepare_excerpt_manifest(source, source, text)

    def test_surrogate_and_empty_source_reject_with_fixed_codes(self):
        for text, code in (("", "INVALID_SOURCE"), ("  \n", "INVALID_SOURCE"), ("x\ud800y", "INVALID_SOURCE")):
            with self.subTest(code=code):
                selected = SourceRecord("s", "r", "a" * 64)
                with self.assertRaisesRegex(ExcerptManifestError, f"^{code}$"):
                    prepare_excerpt_manifest(selected, selected, text)

    def test_unicode_error_never_retains_private_text_in_exception_chain(self):
        text = "PRIVATE_CANARY_SHOULD_NOT_REACH_TELEMETRY\ud800tail"
        selected = SourceRecord("s", "r", "a" * 64)
        with self.assertRaises(ExcerptManifestError) as caught:
            prepare_excerpt_manifest(selected, selected, text)
        exc = caught.exception
        self.assertEqual(str(exc), "INVALID_SOURCE")
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        self.assertNotIn("PRIVATE_CANARY", repr(exc))

    def test_malformed_records_rejected_without_echoing_values(self):
        text = "The river waited."
        record = _record(text)
        for wrong in (
            SourceRecord("secret\nline", "rev", record.source_sha256),
            SourceRecord("id", "", record.source_sha256),
            SourceRecord("id", "rev", "not-a-hash"),
        ):
            with self.subTest(record=wrong):
                with self.assertRaisesRegex(ExcerptManifestError, "^INVALID_RECORD$"):
                    prepare_excerpt_manifest(wrong, wrong, text)

    def test_repr_errors_and_sanitized_report_never_expose_private_fields(self):
        canary = "SECRET_DIALOGUE_DO_NOT_PRINT"
        text = canary + " beneath the rain."
        selected = _record(text, source_id="secret-id", revision_id="secret-revision")
        result = prepare_excerpt_manifest(selected, selected, text, max_excerpt_chars=10)
        report = result.report()
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["coverage"], "EXACT_CONTIGUOUS")
        self.assertEqual(report["issue_codes"], ())
        for printable in (repr(result), repr(result.excerpts), repr(result.excerpts[0]), repr(selected), repr(report)):
            for value in (canary, "secret-id", "secret-revision", selected.source_sha256):
                self.assertNotIn(value, printable)
        with self.assertRaises(ExcerptManifestError) as caught:
            prepare_excerpt_manifest(selected, selected, text + "NEW")
        self.assertEqual(str(caught.exception), "SOURCE_HASH_MISMATCH")
        self.assertNotIn(canary, repr(caught.exception))

    def test_no_filesystem_network_provider_or_stdout_side_effects(self):
        text = "A silent passage waits."
        source = _record(text)
        with patch("builtins.open", side_effect=AssertionError("io")), \
             patch("socket.socket", side_effect=AssertionError("net")), \
             patch("builtins.print", side_effect=AssertionError("stdout")):
            result = prepare_excerpt_manifest(source, source, text)
        self.assertEqual(result.excerpts[0].text, text)


if __name__ == "__main__":
    unittest.main()
