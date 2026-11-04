"""Deterministic in-memory continuity checks for a scene-by-scene manuscript.

All IDs, source texts, character-goal assertions and state claims are caller
supplied. This module neither reads files nor calls models, networks, or Git.
Its checks can falsify some *declared* relationships, but cannot establish
causality, character depth or literary merit from the prose itself. The report
contains only fixed issue codes and counts: never manuscript text or IDs.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, TypedDict


GRAPH_SCHEMA = "aeonith.scene_graph.v1"
AUDIT_SCHEMA = "aeonith.scene_graph_audit.v1"
MAX_CANTOS = 100
MAX_SCENES = 400
MAX_SOURCE_CHARS = 12_000
MAX_ANCHORS_PER_SCENE = 20
MAX_CHANGES_PER_SCENE = 30
MAX_GOALS_PER_SCENE = 20
MAX_COST_EVENTS_PER_SCENE = 20
MAX_LINKS = 1_000
MAX_COMPANIONS = 20
UNKNOWN = "UNKNOWN"

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_GRAPH_KEYS = frozenset({"schema_version", "work_id", "narrator_id",
                         "companions", "other_characters", "expected_canto_count", "cantos",
                         "scenes", "links"})
_CANTO_KEYS = frozenset({"book_id", "canto_id", "position"})
_SCENE_KEYS = frozenset({"book_id", "canto_id", "scene_id", "position",
                         "chronology_position", "revision_id", "source_text", "source_sha256",
                         "anchors", "goals", "changes", "cost_events"})
_ANCHOR_KEYS = frozenset({"quote", "start", "end", "source_sha256"})
_GOAL_KEYS = frozenset({"owner_id", "goal_id", "narrator_relation"})
_CHANGE_KEYS = frozenset({"domain", "entity_id", "before", "after", "anchor_index"})
_COST_KEYS = frozenset({"cost_id", "bearer_id", "action", "cost_type", "anchor_index"})
_LINK_KEYS = frozenset({"from_scene", "to_scene", "kind"})


class QuoteAnchor(TypedDict):
    quote: str
    start: int  # Unicode code points, half-open
    end: int
    source_sha256: str


class StateChange(TypedDict):
    domain: str  # injury | object | location
    entity_id: str
    before: str  # bounded opaque state ID or UNKNOWN
    after: str
    anchor_index: int  # textual anchor position in source scene


class Goal(TypedDict):
    owner_id: str
    goal_id: str
    narrator_relation: str  # independent | dependent | UNKNOWN


class CostEvent(TypedDict):
    cost_id: str
    bearer_id: str  # a registered character; caller assertion only
    action: str  # incur | resolve
    cost_type: str  # reversible | irreversible | UNKNOWN
    anchor_index: int  # points to an exact quote anchor of this scene


class Scene(TypedDict):
    book_id: str
    canto_id: str
    scene_id: str
    position: int  # 1-based within canto
    chronology_position: int | str  # global event time; UNKNOWN permitted
    revision_id: str
    source_text: str
    source_sha256: str
    anchors: list[QuoteAnchor]
    goals: list[Goal]
    changes: list[StateChange]
    cost_events: list[CostEvent]


class SceneGraphError(ValueError):
    """Invalid shape or bounds; messages never contain user text or IDs."""


def _exact(obj: Any, expected: frozenset[str]) -> dict:
    if type(obj) is not dict or set(obj) != expected:
        raise SceneGraphError("invalid graph structure")
    return obj


def _id(value: Any) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _list(value: Any, maximum: int) -> list:
    if type(value) is not list or len(value) > maximum:
        raise SceneGraphError("invalid graph list")
    return value


def _position(value: Any, maximum: int) -> bool:
    return type(value) is int and 1 <= value <= maximum


def _source_hash(text: str) -> str | None:
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeError:
        return None


def _cycles(nodes: set[str], edges: set[tuple[str, str]]) -> bool:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    entered: set[str] = set()
    finished: set[str] = set()

    def visit(node: str) -> bool:
        if node in entered:
            return True
        if node in finished:
            return False
        entered.add(node)
        for other in adjacency[node]:
            if visit(other):
                return True
        entered.remove(node)
        finished.add(node)
        return False

    return any(visit(node) for node in nodes if node not in finished)


def audit_scene_graph(value: Any) -> dict[str, Any]:
    """Audit one caller-declared graph and return issue codes only.

    A no-issues result means no *declared structural contradiction detected*.
    It is never a claim of story coherence, clinical truth, or verified source.
    """
    graph = _exact(value, _GRAPH_KEYS)
    if (graph["schema_version"] != GRAPH_SCHEMA
            or not _id(graph["work_id"]) or not _id(graph["narrator_id"])
            or not _position(graph["expected_canto_count"], MAX_CANTOS)):
        raise SceneGraphError("invalid graph identity or canto limit")
    expected_count = graph["expected_canto_count"]
    companions = _list(graph["companions"], MAX_COMPANIONS)
    if (any(not _id(item) or item == graph["narrator_id"] for item in companions)
            or len(set(companions)) != len(companions)):
        raise SceneGraphError("invalid companion identities")
    other_characters = _list(graph["other_characters"], MAX_COMPANIONS)
    if any(not _id(item) for item in other_characters):
        raise SceneGraphError("invalid character registry")
    known_characters = {graph["narrator_id"], *companions, *other_characters}
    if len(known_characters) != 1 + len(companions) + len(other_characters):
        raise SceneGraphError("invalid character registry")
    cantos = _list(graph["cantos"], MAX_CANTOS)
    scenes = _list(graph["scenes"], MAX_SCENES)
    links = _list(graph["links"], MAX_LINKS)
    codes: set[str] = set()

    canto_by_id: dict[str, dict] = {}
    positions: list[int] = []
    for item in cantos:
        canto = _exact(item, _CANTO_KEYS)
        if not _id(canto["book_id"]) or not _id(canto["canto_id"]) \
                or not _position(canto["position"], MAX_CANTOS):
            raise SceneGraphError("invalid canto metadata")
        if canto["canto_id"] in canto_by_id:
            codes.add("duplicate_canto_id")
        else:
            canto_by_id[canto["canto_id"]] = canto
        positions.append(canto["position"])
        if canto["position"] > expected_count:
            codes.add("canto_out_of_range")
    if len(set(positions)) != len(positions):
        codes.add("duplicate_canto_position")
    if set(positions) != set(range(1, expected_count + 1)):
        codes.add("canto_gap")

    scene_by_id: dict[str, Scene] = {}
    scene_positions: dict[str, list[int]] = {}
    goal_owners: dict[str, str] = {}
    for item in scenes:
        scene = _exact(item, _SCENE_KEYS)
        if (any(not _id(scene[key]) for key in
                ("book_id", "canto_id", "scene_id", "revision_id"))
                or not _position(scene["position"], MAX_SCENES)
                or not (scene["chronology_position"] == UNKNOWN
                        or _position(scene["chronology_position"], MAX_SCENES))):
            raise SceneGraphError("invalid scene metadata")
        if scene["scene_id"] in scene_by_id:
            codes.add("duplicate_scene_id")
        else:
            scene_by_id[scene["scene_id"]] = scene
        scene_positions.setdefault(scene["canto_id"], []).append(scene["position"])
        canto = canto_by_id.get(scene["canto_id"])
        if canto is None:
            codes.add("unknown_canto")
        elif canto["book_id"] != scene["book_id"]:
            codes.add("scene_book_mismatch")

        text, declared = scene["source_text"], scene["source_sha256"]
        if type(text) is not str or not 0 < len(text) <= MAX_SOURCE_CHARS or not text.strip() \
                or type(declared) is not str or not _SHA.fullmatch(declared):
            raise SceneGraphError("invalid bounded source")
        observed_hash = _source_hash(text)
        if observed_hash is None:
            codes.add("invalid_utf8_source")
        elif observed_hash != declared:
            codes.add("source_hash_mismatch")

        for item_anchor in _list(scene["anchors"], MAX_ANCHORS_PER_SCENE):
            anchor = _exact(item_anchor, _ANCHOR_KEYS)
            if (type(anchor["source_sha256"]) is not str
                    or not _SHA.fullmatch(anchor["source_sha256"])):
                raise SceneGraphError("invalid source anchor hash")
            if anchor["source_sha256"] != declared:
                codes.add("stale_anchor_revision")
            quote, start, end = anchor["quote"], anchor["start"], anchor["end"]
            if type(quote) is not str or not quote.strip() or len(quote) > 500:
                raise SceneGraphError("invalid source quote")
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(text) or text[start:end] != quote):
                codes.add("anchor_span_mismatch")
            if _source_hash(quote) is None:
                codes.add("invalid_utf8_anchor")

        for goal in _list(scene["goals"], MAX_GOALS_PER_SCENE):
            row = _exact(goal, _GOAL_KEYS)
            if (not _id(row["owner_id"]) or not _id(row["goal_id"])
                    or row["narrator_relation"] not in ("independent", "dependent", UNKNOWN)):
                raise SceneGraphError("invalid character goal")
            if row["owner_id"] not in known_characters:
                codes.add("unregistered_goal_owner")
            prior_owner = goal_owners.get(row["goal_id"])
            if prior_owner is not None and prior_owner != row["owner_id"]:
                codes.add("goal_owner_conflict")
            goal_owners.setdefault(row["goal_id"], row["owner_id"])
        seen_changes: set[tuple[str, str]] = set()
        for change in _list(scene["changes"], MAX_CHANGES_PER_SCENE):
            row = _exact(change, _CHANGE_KEYS)
            if (row["domain"] not in ("injury", "object", "location")
                    or not _id(row["entity_id"])
                    or type(row["anchor_index"]) is not int
                    or any(state != UNKNOWN and not _id(state)
                           for state in (row["before"], row["after"]))):
                raise SceneGraphError("invalid state transition")
            if not 0 <= row["anchor_index"] < len(scene["anchors"]):
                codes.add("state_event_unanchored")
            state_id = (row["domain"], row["entity_id"])
            if state_id in seen_changes:
                codes.add("duplicate_scene_transition")
            seen_changes.add(state_id)
            if row["before"] == row["after"] == UNKNOWN:
                codes.add("uninformative_transition")
        for event in _list(scene["cost_events"], MAX_COST_EVENTS_PER_SCENE):
            row = _exact(event, _COST_KEYS)
            if (not _id(row["cost_id"]) or not _id(row["bearer_id"])
                    or row["action"] not in ("incur", "resolve")
                    or row["cost_type"] not in ("reversible", "irreversible", UNKNOWN)
                    or type(row["anchor_index"]) is not int):
                raise SceneGraphError("invalid cost event")
            if not 0 <= row["anchor_index"] < len(scene["anchors"]):
                codes.add("cost_event_unanchored")
            if row["bearer_id"] not in known_characters:
                codes.add("unregistered_cost_bearer")
            if row["action"] == "incur" and row["cost_type"] == UNKNOWN:
                codes.add("cost_type_unknown")

    for canto_id, scene_indices in scene_positions.items():
        if len(set(scene_indices)) != len(scene_indices):
            codes.add("duplicate_scene_position")
        if set(scene_indices) != set(range(1, max(scene_indices) + 1)):
            codes.add("scene_gap")
    for canto_id in canto_by_id:
        if canto_id not in scene_positions:
            codes.add("empty_canto")

    # Sorting uses the declared canto and scene positions; unknown cantos are
    # omitted from temporal checks and already surfaced above.
    ordered_scenes = sorted(
        (scene for scene in scene_by_id.values() if scene["canto_id"] in canto_by_id),
        key=lambda s: (canto_by_id[s["canto_id"]]["position"], s["position"],
                       s["scene_id"]),
    )
    rank = {scene["scene_id"]: index for index, scene in enumerate(ordered_scenes)}
    known_chronology = [scene["chronology_position"] for scene in ordered_scenes
                        if scene["chronology_position"] != UNKNOWN]
    if len(known_chronology) != len(set(known_chronology)):
        codes.add("duplicate_chronology_position")
    if len(known_chronology) != len(ordered_scenes):
        codes.add("chronology_unknown")
    ordered_edges: set[tuple[str, str]] = set()
    causal_edges: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    for item in links:
        link = _exact(item, _LINK_KEYS)
        if (not _id(link["from_scene"]) or not _id(link["to_scene"])
                or link["kind"] not in ("ordered", "causal")):
            raise SceneGraphError("invalid graph link")
        source, target, kind = link["from_scene"], link["to_scene"], link["kind"]
        if (source, target, kind) in seen_edges:
            codes.add("duplicate_link")
        seen_edges.add((source, target, kind))
        if source not in rank or target not in rank:
            codes.add("unknown_link_scene")
            continue
        if kind == "ordered":
            ordered_edges.add((source, target))
            if rank[target] != rank[source] + 1:
                codes.add("nonadjacent_ordered_link")
        else:
            causal_edges.add((source, target))
            chronology_from = scene_by_id[source]["chronology_position"]
            chronology_to = scene_by_id[target]["chronology_position"]
            if (chronology_from != UNKNOWN and chronology_to != UNKNOWN
                    and chronology_to <= chronology_from):
                codes.add("causal_back_edge")
    expected_edges = {(a["scene_id"], b["scene_id"])
                      for a, b in zip(ordered_scenes, ordered_scenes[1:])}
    if expected_edges - ordered_edges:
        codes.add("ordered_link_gap")
    if _cycles(set(rank), ordered_edges):
        codes.add("order_cycle")
    if _cycles(set(rank), causal_edges):
        codes.add("causal_cycle")

    declared_independent: set[str] = set()
    last_state: dict[tuple[str, str], str] = {}
    open_costs: dict[str, tuple[str, str]] = {}
    # Physical state and costs follow event chronology, never reading order.
    # UNKNOWN events cannot reliably advance either state ledger.
    chronological_scenes = sorted(
        ordered_scenes,
        key=lambda s: (s["chronology_position"] == UNKNOWN,
                       s["chronology_position"] if s["chronology_position"] != UNKNOWN else MAX_SCENES + 1),
    )
    for scene in chronological_scenes:
        for goal in scene["goals"]:
            if goal["owner_id"] in companions and goal["narrator_relation"] == "independent":
                declared_independent.add(goal["owner_id"])
        if scene["chronology_position"] == UNKNOWN:
            if scene["changes"] or scene["cost_events"]:
                codes.add("temporal_state_unassessed")
            continue
        for change in scene["changes"]:
            state_id = (change["domain"], change["entity_id"])
            prior = last_state.get(state_id, UNKNOWN)
            if (prior != UNKNOWN and change["before"] != UNKNOWN
                    and prior != change["before"]):
                codes.add("state_mismatch")
            # UNKNOWN means absent observation, not evidence that an injury,
            # object, or location magically reset to a blank state.
            if change["after"] != UNKNOWN:
                last_state[state_id] = change["after"]
        for event in scene["cost_events"]:
            cost_id = event["cost_id"]
            if event["action"] == "incur":
                if cost_id in open_costs:
                    codes.add("duplicate_open_cost")
                else:
                    open_costs[cost_id] = event["cost_type"], event["bearer_id"]
            elif cost_id not in open_costs:
                codes.add("cost_resolution_without_incur")
            elif open_costs[cost_id][1] != event["bearer_id"]:
                codes.add("cost_bearer_conflict")
            elif open_costs[cost_id][0] == "irreversible":
                codes.add("irreversible_cost_resolution")
            elif (event["cost_type"] != UNKNOWN
                  and event["cost_type"] != open_costs[cost_id][0]):
                codes.add("cost_type_mismatch")
            else:
                del open_costs[cost_id]
    if set(companions) - declared_independent:
        codes.add("companion_independent_goal_unestablished")
    # Open obligations are legitimate plot state. Surface them separately from
    # structural contradictions; no automatic closure is justified.
    carry_codes = ["unresolved_cost_carry"] if open_costs else []

    return {
        "schema_version": AUDIT_SCHEMA,
        "structural_status": "issues_detected" if codes else "no_declared_contradictions_detected",
        "semantic_quality": "UNASSESSED", "source_provenance": "USER",
        "issue_codes": sorted(codes),
        "carry_codes": carry_codes,
        "counts": {"declared_expected_cantos": expected_count,
                   "cantos": len(cantos), "scenes": len(scenes),
                   "links": len(links), "open_costs": len(open_costs),
                   "companions_without_declared_independent_goal":
                       len(set(companions) - declared_independent)},
        "limitations": [
            "Declarations, goals, state labels and links are caller-supplied, not verified literary facts.",
            "An absence of issue codes does not establish narrative coherence or quality.",
            "Only source anchors are checked against supplied text; no external source or reviewer is authenticated.",
        ],
    }
