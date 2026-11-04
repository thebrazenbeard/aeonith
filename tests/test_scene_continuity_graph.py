"""Synthetic-only, offline adversarial tests for scene continuity claims."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from aeonith.scene_continuity_graph import (
    AUDIT_SCHEMA, GRAPH_SCHEMA, SceneGraphError, audit_scene_graph,
)


SOURCE = "🐸 The gate opened. The path continued."


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scene(n: int, *, text: str = SOURCE) -> dict:
    return {
        "book_id": "Book1" if n <= 34 else "Book2" if n <= 67 else "Book3",
        "canto_id": f"C{n:03d}", "scene_id": f"S{n:03d}", "position": 1,
        "chronology_position": n, "revision_id": "r1", "source_text": text,
        "source_sha256": digest(text),
        "anchors": [{"quote": "🐸", "start": 0, "end": 1,
                     "source_sha256": digest(text)}],
        "goals": [], "changes": [], "cost_events": [],
    }


def graph(count: int = 100) -> dict:
    scenes = [scene(index) for index in range(1, count + 1)]
    scenes[0]["goals"].append({
        "owner_id": "burl", "goal_id": "protect-ferry", "narrator_relation": "independent",
    })
    return {
        "schema_version": GRAPH_SCHEMA, "work_id": "synthetic-novel",
        "narrator_id": "narrator", "companions": ["burl"], "other_characters": [],
        "expected_canto_count": count,
        "cantos": [{"book_id": item["book_id"], "canto_id": item["canto_id"],
                    "position": index}
                   for index, item in enumerate(scenes, start=1)],
        "scenes": scenes,
        "links": [{"from_scene": f"S{index:03d}", "to_scene": f"S{index+1:03d}",
                   "kind": "ordered"}
                  for index in range(1, count)],
    }


class CanonicalSpanTests(unittest.TestCase):
    def test_unique_ordered_hundred_canto_spine(self) -> None:
        result = audit_scene_graph(graph(100))
        self.assertEqual(result["schema_version"], AUDIT_SCHEMA)
        self.assertEqual(result["counts"]["cantos"], 100)
        self.assertEqual(result["counts"]["scenes"], 100)
        self.assertEqual(result["counts"]["links"], 99)
        self.assertEqual(result["issue_codes"], [])
        self.assertEqual(result["structural_status"], "no_declared_contradictions_detected")
        self.assertEqual(result["semantic_quality"], "UNASSESSED")

    def test_missing_canto_and_missing_ordered_link(self) -> None:
        value = graph(100)
        value["cantos"].pop(47)
        value["scenes"].pop(47)
        value["links"] = [row for row in value["links"]
                          if "S048" not in (row["from_scene"], row["to_scene"])]
        codes = audit_scene_graph(value)["issue_codes"]
        self.assertIn("canto_gap", codes)
        self.assertIn("ordered_link_gap", codes)

    def test_duplicate_canto_position_and_id(self) -> None:
        value = graph(3)
        value["cantos"][1]["position"] = 1
        value["cantos"][2]["canto_id"] = "C001"
        codes = audit_scene_graph(value)["issue_codes"]
        self.assertIn("duplicate_canto_position", codes)
        self.assertIn("duplicate_canto_id", codes)

    def test_order_and_causal_cycles_detected(self) -> None:
        value = graph(3)
        value["links"].extend([
            {"from_scene": "S003", "to_scene": "S001", "kind": "ordered"},
            {"from_scene": "S001", "to_scene": "S003", "kind": "causal"},
            {"from_scene": "S003", "to_scene": "S001", "kind": "causal"},
        ])
        codes = audit_scene_graph(value)["issue_codes"]
        self.assertIn("order_cycle", codes)
        self.assertIn("causal_cycle", codes)
        self.assertIn("causal_back_edge", codes)
        self.assertIn("nonadjacent_ordered_link", codes)

    def test_causal_forward_link_can_skip_adjacent_scenes(self) -> None:
        value = graph(3)
        value["links"].append({
            "from_scene": "S001", "to_scene": "S003", "kind": "causal",
        })
        self.assertEqual(audit_scene_graph(value)["issue_codes"], [])

    def test_presentation_order_is_not_flashback_chronology(self) -> None:
        value = graph(3)
        # Scene 3 is presented last but occurs before the first two scenes.
        for row, chronology in zip(value["scenes"], (2, 3, 1)):
            row["chronology_position"] = chronology
        value["links"].append({
            "from_scene": "S003", "to_scene": "S001", "kind": "causal",
        })
        value["scenes"][2]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "UNKNOWN",
            "after": "unhurt", "anchor_index": 0,
        })
        value["scenes"][0]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "unhurt",
            "after": "injured", "anchor_index": 0,
        })
        value["scenes"][1]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "injured",
            "after": "healed", "anchor_index": 0,
        })
        codes = audit_scene_graph(value)["issue_codes"]
        self.assertNotIn("causal_back_edge", codes)
        self.assertNotIn("state_mismatch", codes)
        self.assertNotIn("order_cycle", codes)


class SourceEvidenceTests(unittest.TestCase):
    def test_exact_unicode_codepoint_anchor_is_valid(self) -> None:
        value = graph(2)
        value["scenes"][0]["source_text"] = "First 🐸 entered"
        value["scenes"][0]["source_sha256"] = digest("First 🐸 entered")
        value["scenes"][0]["anchors"] = [{
            "quote": "🐸", "start": 6, "end": 7,
            "source_sha256": digest("First 🐸 entered"),
        }]
        self.assertEqual(audit_scene_graph(value)["issue_codes"], [])

    def test_stale_revision_anchor_detected_even_if_quote_still_present(self) -> None:
        value = graph(2)
        new_text = "Now 🐸 The gate opened. The path continued."
        value["scenes"][0]["source_text"] = new_text
        value["scenes"][0]["source_sha256"] = digest(new_text)
        # Prior anchor hash and offset point to an old revision.
        codes = audit_scene_graph(value)["issue_codes"]
        self.assertIn("stale_anchor_revision", codes)
        self.assertIn("anchor_span_mismatch", codes)

    def test_source_text_hash_mismatch_and_invalid_unicode_are_detected(self) -> None:
        value = graph(2)
        value["scenes"][1]["source_text"] = "tampered"
        self.assertIn("source_hash_mismatch", audit_scene_graph(value)["issue_codes"])
        value["scenes"][1]["source_text"] = "unpaired \ud800"
        self.assertIn("invalid_utf8_source", audit_scene_graph(value)["issue_codes"])

    def test_failed_input_and_report_never_echo_manuscript_text_or_ids(self) -> None:
        secret = "PATRICK_PRIVATE_MANUSCRIPT_SENTINEL"
        value = graph(2)
        value["scenes"][0]["source_text"] = secret
        report = audit_scene_graph(value)
        encoded = json.dumps(report)
        self.assertNotIn(secret, encoded)
        for private_id in ("synthetic-novel", "narrator", "burl", "C001", "S001"):
            self.assertNotIn(private_id, encoded)
        value["scenes"][0]["source_text"] = 47
        with self.assertRaises(SceneGraphError) as captured:
            audit_scene_graph(value)
        self.assertNotIn(secret, str(captured.exception))


class CharacterAndStateTests(unittest.TestCase):
    def test_companion_goal_must_be_explicitly_owned_and_independent(self) -> None:
        value = graph(3)
        value["scenes"][0]["goals"][0]["narrator_relation"] = "dependent"
        report = audit_scene_graph(value)
        self.assertIn("companion_independent_goal_unestablished", report["issue_codes"])
        self.assertEqual(report["counts"]["companions_without_declared_independent_goal"], 1)
        # Narrator goals cannot substitute for independent companion goals.
        value["scenes"][0]["goals"][0]["owner_id"] = "narrator"
        value["scenes"][0]["goals"][0]["narrator_relation"] = "independent"
        self.assertIn("companion_independent_goal_unestablished",
                      audit_scene_graph(value)["issue_codes"])

    def test_unregistered_character_cannot_assert_independent_goal(self) -> None:
        value = graph(2)
        value["scenes"][0]["goals"].append({
            "owner_id": "made-up-actor", "goal_id": "find-ferry",
            "narrator_relation": "independent",
        })
        self.assertIn("unregistered_goal_owner", audit_scene_graph(value)["issue_codes"])

    def test_goal_identity_cannot_switch_owners_across_scenes(self) -> None:
        value = graph(2)
        value["other_characters"] = ["mira"]
        value["scenes"][1]["goals"].append({
            "owner_id": "mira", "goal_id": "protect-ferry",
            "narrator_relation": "independent",
        })
        self.assertIn("goal_owner_conflict", audit_scene_graph(value)["issue_codes"])

    def test_unhashable_character_registry_fails_without_raw_exception(self) -> None:
        value = graph(2)
        value["other_characters"] = [["untrusted"]]
        with self.assertRaisesRegex(SceneGraphError, "invalid character registry"):
            audit_scene_graph(value)

    def test_state_mismatch_across_scenes(self) -> None:
        value = graph(3)
        value["scenes"][0]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "unhurt", "after": "injured",
            "anchor_index": 0,
        })
        value["scenes"][1]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "unhurt", "after": "healed",
            "anchor_index": 0,
        })
        self.assertIn("state_mismatch", audit_scene_graph(value)["issue_codes"])
        value["scenes"][1]["changes"][0]["before"] = "UNKNOWN"
        self.assertNotIn("state_mismatch", audit_scene_graph(value)["issue_codes"])

    def test_injury_object_location_transitions_keep_independent_state(self) -> None:
        value = graph(3)
        for domain in ("injury", "object", "location"):
            value["scenes"][0]["changes"].append({
                "domain": domain, "entity_id": "burl", "before": "UNKNOWN",
                "after": "known", "anchor_index": 0,
            })
            value["scenes"][1]["changes"].append({
                "domain": domain, "entity_id": "burl", "before": "known",
                "after": "changed", "anchor_index": 0,
            })
        self.assertNotIn("state_mismatch", audit_scene_graph(value)["issue_codes"])

    def test_unknown_observation_does_not_erase_prior_known_state(self) -> None:
        value = graph(3)
        value["scenes"][0]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "unhurt",
            "after": "injured", "anchor_index": 0,
        })
        value["scenes"][1]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "UNKNOWN",
            "after": "UNKNOWN", "anchor_index": 0,
        })
        value["scenes"][2]["changes"].append({
            "domain": "injury", "entity_id": "burl", "before": "unhurt",
            "after": "healed", "anchor_index": 0,
        })
        codes = audit_scene_graph(value)["issue_codes"]
        self.assertIn("uninformative_transition", codes)
        self.assertIn("state_mismatch", codes)

    def test_unresolved_cost_carries_until_explicit_resolution(self) -> None:
        value = graph(3)
        value["scenes"][0]["cost_events"].append({
            "cost_id": "sacrificed-shield", "bearer_id": "burl", "action": "incur",
            "cost_type": "reversible", "anchor_index": 0,
        })
        report = audit_scene_graph(value)
        self.assertIn("unresolved_cost_carry", report["carry_codes"])
        self.assertNotIn("unresolved_cost_carry", report["issue_codes"])
        self.assertEqual(report["counts"]["open_costs"], 1)
        value["scenes"][2]["cost_events"].append({
            "cost_id": "sacrificed-shield", "bearer_id": "burl", "action": "resolve",
            "cost_type": "reversible", "anchor_index": 0,
        })
        report = audit_scene_graph(value)
        self.assertNotIn("unresolved_cost_carry", report["carry_codes"])
        self.assertEqual(report["counts"]["open_costs"], 0)

    def test_resolution_without_cost_is_flagged(self) -> None:
        value = graph(2)
        value["scenes"][0]["cost_events"].append({
            "cost_id": "invented-cost", "bearer_id": "burl", "action": "resolve",
            "cost_type": "UNKNOWN", "anchor_index": 0,
        })
        self.assertIn("cost_resolution_without_incur", audit_scene_graph(value)["issue_codes"])

    def test_irreversible_cost_cannot_be_erased_by_resolution(self) -> None:
        value = graph(3)
        value["scenes"][0]["cost_events"].append({
            "cost_id": "fallen-guardian", "bearer_id": "burl", "action": "incur",
            "cost_type": "irreversible", "anchor_index": 0,
        })
        value["scenes"][2]["cost_events"].append({
            "cost_id": "fallen-guardian", "bearer_id": "burl", "action": "resolve",
            "cost_type": "reversible", "anchor_index": 0,
        })
        report = audit_scene_graph(value)
        self.assertIn("irreversible_cost_resolution", report["issue_codes"])
        self.assertIn("unresolved_cost_carry", report["carry_codes"])
        self.assertEqual(report["counts"]["open_costs"], 1)

    def test_cost_cannot_be_transferred_to_other_bearer_on_resolution(self) -> None:
        value = graph(2)
        value["other_characters"] = ["mira"]
        value["scenes"][0]["cost_events"].append({
            "cost_id": "lost-token", "bearer_id": "burl", "action": "incur",
            "cost_type": "reversible", "anchor_index": 0,
        })
        value["scenes"][1]["cost_events"].append({
            "cost_id": "lost-token", "bearer_id": "mira", "action": "resolve",
            "cost_type": "reversible", "anchor_index": 0,
        })
        report = audit_scene_graph(value)
        self.assertIn("cost_bearer_conflict", report["issue_codes"])
        self.assertEqual(report["counts"]["open_costs"], 1)

    def test_unanchored_cost_event_is_flagged(self) -> None:
        value = graph(2)
        value["scenes"][0]["cost_events"].append({
            "cost_id": "loss", "bearer_id": "burl", "action": "incur",
            "cost_type": "reversible",
            "anchor_index": 99,
        })
        self.assertIn("cost_event_unanchored", audit_scene_graph(value)["issue_codes"])

    def test_untrusted_graph_cannot_supply_external_commands(self) -> None:
        value = graph(2)
        value["provider_url"] = "https://example.invalid"
        with self.assertRaises(SceneGraphError):
            audit_scene_graph(value)

    def test_audit_has_no_hidden_file_network_or_subprocess_operations(self) -> None:
        with patch("builtins.open", side_effect=AssertionError("filesystem accessed")), \
                patch("socket.socket", side_effect=AssertionError("network accessed")), \
                patch("subprocess.run", side_effect=AssertionError("subprocess accessed")):
            self.assertEqual(audit_scene_graph(graph(3))["issue_codes"], [])


if __name__ == "__main__":
    unittest.main()
