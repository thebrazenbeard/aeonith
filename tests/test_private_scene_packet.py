"""Synthetic falsifiers for private, source-exact scene boundary packets."""

import hashlib
import unittest
from dataclasses import replace
from unittest.mock import patch

from aeonith.editorial_excerpt_manifest import SourceRecord, prepare_excerpt_manifest
from aeonith.private_scene_packet import (
    PrivateScenePacketError,
    SceneSpan,
    prepare_private_scene_packet,
)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fixture(text, chunk=6):
    selected = SourceRecord("work.canto.001", "draft.7", _sha(text))
    return prepare_excerpt_manifest(selected, selected, text, max_excerpt_chars=chunk)


def _scene(text, scene_id, start, end):
    return SceneSpan(scene_id, start, end, _sha(text[start:end]))


class ScenePacketTests(unittest.TestCase):
    def test_exact_full_scene_coverage_maps_many_excerpts_not_one_scene_per_excerpt(self):
        text = "Rain🌧 fell; then a door shut."
        manifest = _fixture(text, chunk=7)
        result = prepare_private_scene_packet(manifest, text, (_scene(text, "s1", 0, len(text)),))
        self.assertEqual(result.coverage, "EXACT_SCENE_COVERAGE")
        self.assertEqual(result.gaps, ())
        self.assertEqual(result.report()["status"], "READY")
        self.assertEqual(result.report()["semantic_quality"], "UNASSESSED")
        self.assertEqual(result.report()["model_status"], "NOT_ATTEMPTED")
        scene = result.scenes[0]
        self.assertEqual(scene.text, text)
        self.assertEqual(scene.start, 0)
        self.assertEqual(scene.end, len(text))
        self.assertGreater(len(scene.intersections), 1)
        self.assertEqual("".join(text[x.source_start:x.source_end] for x in scene.intersections), scene.text)
        self.assertEqual(scene.intersections[0].scene_start, 0)
        self.assertEqual(scene.intersections[-1].scene_end, len(text))

    def test_two_scenes_can_split_inside_one_excerpt_with_exact_intersections(self):
        text = "ABCDEFGH🌊IJKL"
        manifest = _fixture(text, chunk=8)
        scenes = (_scene(text, "left", 0, 5), _scene(text, "right", 5, len(text)))
        result = prepare_private_scene_packet(manifest, text, scenes)
        self.assertEqual(result.report()["scene_count"], 2)
        self.assertEqual(result.scenes[0].intersections[0].excerpt_index, 0)
        self.assertEqual(result.scenes[1].intersections[0].excerpt_index, 0)
        self.assertEqual(result.scenes[1].intersections[0].source_start, 5)
        self.assertEqual(result.scenes[1].intersections[0].scene_start, 0)
        self.assertEqual("".join(s.text for s in result.scenes), text)

    def test_stale_source_hash_rejected_even_when_excerpt_metadata_matches_old_text(self):
        text = "A true passage, unchanged."
        manifest = _fixture(text)
        with self.assertRaisesRegex(PrivateScenePacketError, "^SOURCE_HASH_MISMATCH$"):
            prepare_private_scene_packet(manifest, text + " altered", (_scene(text, "s1", 0, len(text)),))

    def test_forged_excerpt_text_and_recomputed_chunk_hash_cannot_pass(self):
        text = "A stable complete manuscript source."
        manifest = _fixture(text)
        first = manifest.excerpts[0]
        changed = "X" + first.text[1:]
        forged = replace(first, text=changed, excerpt_sha256=_sha(changed))
        attacked = replace(manifest, excerpts=(forged, *manifest.excerpts[1:]))
        with self.assertRaisesRegex(PrivateScenePacketError, "^MANIFEST_MISMATCH$"):
            prepare_private_scene_packet(attacked, text, (_scene(text, "scene1", 0, len(text)),))

    def test_forged_excerpt_offsets_and_source_revision_rejected(self):
        text = "Another stable scene under night."
        manifest = _fixture(text)
        moved = replace(manifest.excerpts[0], start=1)
        wrong_offsets = replace(manifest, excerpts=(moved, *manifest.excerpts[1:]))
        wrong_rev = replace(manifest.excerpts[0], revision_id="different")
        wrong_revision = replace(manifest, excerpts=(wrong_rev, *manifest.excerpts[1:]))
        for attacked in (wrong_offsets, wrong_revision):
            with self.subTest(attacked=attacked):
                with self.assertRaisesRegex(PrivateScenePacketError, "^MANIFEST_MISMATCH$"):
                    prepare_private_scene_packet(attacked, text, (_scene(text, "s1", 0, len(text)),))

    def test_malformed_unhashable_boundary_and_surrogate_metadata_do_not_escape(self):
        text = "Verified source content."
        manifest = _fixture(text)
        wrong_boundary = replace(manifest.excerpts[0], boundary=["PRIVATE-CANARY"])
        wrong_record = SourceRecord("PRIVATE\ud800", "rev", _sha(text))
        variants = (
            replace(manifest, excerpts=(wrong_boundary, *manifest.excerpts[1:])),
            replace(manifest, source_record=wrong_record),
        )
        for attacked in variants:
            with self.subTest(attacked=type(attacked).__name__):
                with self.assertRaises(PrivateScenePacketError) as caught:
                    prepare_private_scene_packet(attacked, text, (_scene(text, "s1", 0, len(text)),))
                self.assertEqual(str(caught.exception), "MANIFEST_MISMATCH")
                self.assertIsNone(caught.exception.__cause__)
                self.assertIsNone(caught.exception.__context__)

    def test_forged_scene_anchor_hash_rejected(self):
        text = "A door stayed shut."
        manifest = _fixture(text)
        wrong = SceneSpan("s1", 0, len(text), "0" * 64)
        with self.assertRaisesRegex(PrivateScenePacketError, "^SCENE_HASH_MISMATCH$"):
            prepare_private_scene_packet(manifest, text, (wrong,))

    def test_scene_overlap_and_out_of_order_rejected(self):
        text = "first and second"
        manifest = _fixture(text)
        variants = (
            ((_scene(text, "one", 0, 8), _scene(text, "two", 7, len(text))), "SCENE_OVERLAP"),
            ((_scene(text, "two", 8, len(text)), _scene(text, "one", 0, 8)), "SCENE_ORDER_INVALID"),
        )
        for scenes, code in variants:
            with self.subTest(code=code):
                with self.assertRaisesRegex(PrivateScenePacketError, f"^{code}$"):
                    prepare_private_scene_packet(manifest, text, scenes)

    def test_default_rejects_scene_gaps_and_explicit_opt_in_reports_partial(self):
        text = "BEGIN MIDDLE END"
        manifest = _fixture(text)
        scenes = (_scene(text, "one", 0, 5), _scene(text, "two", 13, len(text)))
        with self.assertRaisesRegex(PrivateScenePacketError, "^SCENE_GAP$"):
            prepare_private_scene_packet(manifest, text, scenes)
        result = prepare_private_scene_packet(manifest, text, scenes, allow_gaps=True)
        self.assertEqual(result.coverage, "PARTIAL_EXPLICIT_GAPS")
        self.assertEqual(result.gaps, ((5, 13),))
        self.assertEqual(result.report()["status"], "PARTIAL")
        self.assertEqual(result.report()["issue_codes"], ("UNSCOPED_SOURCE_SPAN",))
        self.assertEqual(result.report()["covered_chars"], len(text) - 8)

    def test_duplicate_scene_id_and_invalid_spans_rejected(self):
        text = "AlphaBetaGamma"
        manifest = _fixture(text)
        cases = (
            ((_scene(text, "same", 0, 5), _scene(text, "same", 5, len(text))), "INVALID_SCENE"),
            ((SceneSpan("id", True, 5, _sha(text[:5])),), "INVALID_SCENE"),
            ((SceneSpan("id", 0, 0, _sha("")),), "INVALID_SCENE"),
            ((SceneSpan("id", 0, len(text) + 1, _sha(text)),), "INVALID_SCENE"),
        )
        for scenes, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(PrivateScenePacketError, f"^{code}$"):
                    prepare_private_scene_packet(manifest, text, scenes)

    def test_whitespace_only_declared_scene_rejected(self):
        text = "FIRST    SECOND"
        manifest = _fixture(text)
        scenes = (_scene(text, "a", 0, 5), _scene(text, "space", 5, 9), _scene(text, "b", 9, len(text)))
        with self.assertRaisesRegex(PrivateScenePacketError, "^UNREVIEWABLE_SCENE$"):
            prepare_private_scene_packet(manifest, text, scenes)

    def test_scene_budget_is_12000_codepoints_even_across_multiple_excerpts(self):
        text = "A" * 12_001
        manifest = _fixture(text, chunk=6_000)
        with self.assertRaisesRegex(PrivateScenePacketError, "^SCENE_TOO_LARGE$"):
            prepare_private_scene_packet(manifest, text, (_scene(text, "too-long", 0, len(text)),))
        result = prepare_private_scene_packet(manifest, text, (
            _scene(text, "first", 0, 12_000),
            _scene(text, "last", 12_000, len(text)),
        ))
        self.assertEqual(result.report()["status"], "READY")

    def test_source_over_limit_and_unexpected_options_fail_closed(self):
        small = "Some passage."
        manifest = _fixture(small)
        with self.assertRaisesRegex(PrivateScenePacketError, "^SOURCE_TOO_LARGE$"):
            prepare_private_scene_packet(manifest, "x" * 1_000_001, ())
        with self.assertRaisesRegex(PrivateScenePacketError, "^SOURCE_TOO_LARGE$"):
            prepare_private_scene_packet(manifest, "🌊" * 800_000, ())
        with self.assertRaisesRegex(PrivateScenePacketError, "^INVALID_SOURCE$"):
            prepare_private_scene_packet(manifest, "Source\x00with forbidden NUL", ())
        with self.assertRaisesRegex(PrivateScenePacketError, "^INVALID_OPTION$"):
            prepare_private_scene_packet(manifest, small, (_scene(small, "s1", 0, len(small)),), allow_gaps="yes")

    def test_private_canaries_not_in_repr_report_or_exception_context(self):
        marker = "SECRET_NARRATOR_CONTENT_DO_NOT_LOG"
        text = marker + " after dark."
        manifest = _fixture(text)
        scene = _scene(text, "SECRET_SCENE_ID", 0, len(text))
        result = prepare_private_scene_packet(manifest, text, (scene,))
        for visible in (repr(result), repr(result.scenes), repr(result.scenes[0]), repr(scene), repr(result.report())):
            for private in (marker, "SECRET_SCENE_ID", manifest.source_record.source_id,
                            manifest.source_record.revision_id, manifest.source_record.source_sha256):
                self.assertNotIn(private, visible)
        with self.assertRaises(PrivateScenePacketError) as caught:
            prepare_private_scene_packet(manifest, marker + "\ud800", (scene,))
        error = caught.exception
        self.assertEqual(str(error), "INVALID_SOURCE")
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertNotIn(marker, repr(error))

    def test_no_filesystem_network_or_stdout_side_effects(self):
        text = "The synthetic source is private."
        manifest = _fixture(text)
        with patch("builtins.open", side_effect=AssertionError("filesystem")), \
             patch("socket.socket", side_effect=AssertionError("network")), \
             patch("builtins.print", side_effect=AssertionError("stdout")):
            result = prepare_private_scene_packet(manifest, text, (_scene(text, "s1", 0, len(text)),))
        self.assertEqual(result.scenes[0].text, text)


if __name__ == "__main__":
    unittest.main()
