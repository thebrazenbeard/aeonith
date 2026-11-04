"""Bind explicit private scene spans to a verified in-memory excerpt manifest.

Scenes come from an externally trusted *caller*, not from excerpt boundaries.
An excerpt can overlap multiple scenes and a scene can cross many excerpts.
The source record is an external custody assertion, not authentication by this
module. No model, transport, filesystem or persistence is used here.

Scene prose, identities, digests and the returned packet are PRIVATE CALLER
MEMORY. Only ``packet.report()`` is suitable for sanitized routine telemetry.
Its deterministic findings do not determine literary or semantic quality.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Sequence

from .editorial_excerpt_manifest import (
    ExcerptManifest,
    MAX_EXCERPTS,
    MAX_EXCERPT_CHARS,
    MAX_SOURCE_CHARS,
    MAX_SOURCE_UTF8_BYTES,
    PreparedExcerpt,
    SCHEMA as EXCERPT_SCHEMA,
    SourceRecord,
)


SCHEMA = "aeonith.private_scene_packet.v1"
MAX_SCENES = 256
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BOUNDARIES = frozenset({"source_end", "paragraph", "limit"})


class PrivateScenePacketError(ValueError):
    """Sanitized fixed-code error without source content or private IDs."""


@dataclass(frozen=True, slots=True, repr=False)
class SceneSpan:
    """Caller-declared half-open code-point span with exact text digest."""

    scene_id: str
    start: int
    end: int
    scene_sha256: str


@dataclass(frozen=True, slots=True)
class ExcerptIntersection:
    """Exact offset relation; does not assert a semantic scene boundary."""

    excerpt_index: int
    source_start: int
    source_end: int
    excerpt_start: int
    excerpt_end: int
    scene_start: int
    scene_end: int


@dataclass(frozen=True, slots=True)
class PreparedScene:
    """Explicit scene and its intersections; text and identity stay private."""

    start: int
    end: int
    intersections: tuple[ExcerptIntersection, ...]
    scene_id: str = field(repr=False)
    scene_sha256: str = field(repr=False)
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ScenePacket:
    """An in-memory source-bound packet; never serialize as a public report."""

    source_chars: int
    excerpt_count: int
    coverage: str
    offset_unit: str
    gaps: tuple[tuple[int, int], ...]
    source_record: SourceRecord = field(repr=False)
    scenes: tuple[PreparedScene, ...] = field(repr=False)
    schema_version: str = SCHEMA
    privacy: str = "PRIVATE_CALLER_MEMORY"

    def report(self) -> dict[str, object]:
        """Return only code and count metadata; never content or source IDs."""
        return {
            "schema_version": SCHEMA,
            "status": "READY" if not self.gaps else "PARTIAL",
            "coverage": self.coverage,
            "offset_unit": self.offset_unit,
            "source_chars": self.source_chars,
            "covered_chars": sum(scene.end - scene.start for scene in self.scenes),
            "gap_count": len(self.gaps),
            "scene_count": len(self.scenes),
            "excerpt_count": self.excerpt_count,
            "issue_codes": () if not self.gaps else ("UNSCOPED_SOURCE_SPAN",),
            "semantic_quality": "UNASSESSED",
            "model_status": "NOT_ATTEMPTED",
            "source_provenance": "CALLER_ASSERTED",
        }


def _utf8_or_none(text: str) -> bytes | None:
    """Contain a UnicodeEncodeError before raising our sanitized exception."""
    try:
        return text.encode("utf-8", "strict")
    except UnicodeError:
        return None


def _valid_record(record: SourceRecord) -> bool:
    return (
        type(record) is SourceRecord
        and type(record.source_id) is str
        and _ID.fullmatch(record.source_id) is not None
        and type(record.revision_id) is str
        and _ID.fullmatch(record.revision_id) is not None
        and type(record.source_sha256) is str
        and _SHA.fullmatch(record.source_sha256) is not None
    )


def _validate_manifest(manifest: ExcerptManifest, text: str, encoded: bytes) -> None:
    if (
        type(manifest) is not ExcerptManifest
        or type(manifest.schema_version) is not str
        or manifest.schema_version != EXCERPT_SCHEMA
        or type(manifest.privacy) is not str
        or manifest.privacy != "PRIVATE_CALLER_MEMORY"
        or type(manifest.coverage) is not str
        or manifest.coverage != "EXACT_CONTIGUOUS"
        or type(manifest.offset_unit) is not str
        or manifest.offset_unit != "unicode_code_points"
        or type(manifest.gaps) is not tuple
        or manifest.gaps != ()
        or type(manifest.source_chars) is not int
        or type(manifest.source_utf8_bytes) is not int
        or not _valid_record(manifest.source_record)
        or type(manifest.excerpts) is not tuple
        or not 1 <= len(manifest.excerpts) <= MAX_EXCERPTS
    ):
        raise PrivateScenePacketError("MANIFEST_MISMATCH")

    if not hmac.compare_digest(hashlib.sha256(encoded).hexdigest(), manifest.source_record.source_sha256):
        raise PrivateScenePacketError("SOURCE_HASH_MISMATCH")
    if manifest.source_chars != len(text) or manifest.source_utf8_bytes != len(encoded):
        raise PrivateScenePacketError("MANIFEST_MISMATCH")

    prior = 0
    for index, excerpt in enumerate(manifest.excerpts):
        if (
            type(excerpt) is not PreparedExcerpt
            or type(excerpt.index) is not int
            or excerpt.index != index
            or type(excerpt.start) is not int
            or type(excerpt.end) is not int
            or excerpt.start != prior
            or not excerpt.start < excerpt.end <= len(text)
            or excerpt.end - excerpt.start > MAX_EXCERPT_CHARS
            or type(excerpt.boundary) is not str
            or excerpt.boundary not in _BOUNDARIES
            or type(excerpt.text) is not str
            or excerpt.text != text[excerpt.start:excerpt.end]
            or not excerpt.text.strip()
            or type(excerpt.source_id) is not str
            or type(excerpt.revision_id) is not str
            or type(excerpt.source_sha256) is not str
            or excerpt.source_id != manifest.source_record.source_id
            or excerpt.revision_id != manifest.source_record.revision_id
            or excerpt.source_sha256 != manifest.source_record.source_sha256
            or type(excerpt.excerpt_sha256) is not str
            or _SHA.fullmatch(excerpt.excerpt_sha256) is None
            or not hmac.compare_digest(
                hashlib.sha256(_encoded_source_slice(text, excerpt.start, excerpt.end)).hexdigest(),
                excerpt.excerpt_sha256,
            )
        ):
            raise PrivateScenePacketError("MANIFEST_MISMATCH")
        prior = excerpt.end
    if prior != len(text):
        raise PrivateScenePacketError("MANIFEST_MISMATCH")


def _encoded_source_slice(text: str, start: int, end: int) -> bytes:
    """Encode a verified Unicode substring; never expose it in errors."""
    return text[start:end].encode("utf-8")


def _scene_intersections(start: int, end: int,
                         excerpts: tuple[PreparedExcerpt, ...]) -> tuple[ExcerptIntersection, ...]:
    refs = []
    for excerpt in excerpts:
        a, b = max(start, excerpt.start), min(end, excerpt.end)
        if a < b:
            refs.append(ExcerptIntersection(
                excerpt_index=excerpt.index,
                source_start=a, source_end=b,
                excerpt_start=a - excerpt.start, excerpt_end=b - excerpt.start,
                scene_start=a - start, scene_end=b - start,
            ))
    return tuple(refs)


def prepare_private_scene_packet(
    manifest: ExcerptManifest,
    text: str,
    scenes: Sequence[SceneSpan],
    *,
    allow_gaps: bool = False,
) -> ScenePacket:
    """Verify source-bound excerpts and explicit scenes; never infer scenes.

    The caller is responsible for authenticating the private source record and
    for declaring *semantic* scene boundaries. A source SHA proves only exact
    text identity, not that a declared scene is narratively meaningful.
    """
    if type(allow_gaps) is not bool:
        raise PrivateScenePacketError("INVALID_OPTION")
    if type(text) is not str or not text:
        raise PrivateScenePacketError("INVALID_SOURCE")
    if len(text) > MAX_SOURCE_CHARS:
        raise PrivateScenePacketError("SOURCE_TOO_LARGE")
    if not text.strip() or "\x00" in text:
        raise PrivateScenePacketError("INVALID_SOURCE")
    encoded = _utf8_or_none(text)
    if encoded is None:
        raise PrivateScenePacketError("INVALID_SOURCE")
    if len(encoded) > MAX_SOURCE_UTF8_BYTES:
        raise PrivateScenePacketError("SOURCE_TOO_LARGE")
    _validate_manifest(manifest, text, encoded)
    if type(scenes) not in (tuple, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise PrivateScenePacketError("INVALID_SCENES")

    prepared = []
    gaps = []
    seen_ids = set()
    prior_start, prior_end = -1, 0
    for scene in scenes:
        if (
            type(scene) is not SceneSpan
            or type(scene.scene_id) is not str
            or _ID.fullmatch(scene.scene_id) is None
            or scene.scene_id in seen_ids
            or type(scene.start) is not int
            or type(scene.end) is not int
            or not 0 <= scene.start < scene.end <= len(text)
            or type(scene.scene_sha256) is not str
            or _SHA.fullmatch(scene.scene_sha256) is None
        ):
            raise PrivateScenePacketError("INVALID_SCENE")
        seen_ids.add(scene.scene_id)
        if scene.end - scene.start > MAX_EXCERPT_CHARS:
            raise PrivateScenePacketError("SCENE_TOO_LARGE")
        if scene.start < prior_start:
            raise PrivateScenePacketError("SCENE_ORDER_INVALID")
        if scene.start < prior_end:
            raise PrivateScenePacketError("SCENE_OVERLAP")
        if scene.start > prior_end:
            gaps.append((prior_end, scene.start))
        piece = text[scene.start:scene.end]
        if not piece.strip():
            raise PrivateScenePacketError("UNREVIEWABLE_SCENE")
        if not hmac.compare_digest(hashlib.sha256(piece.encode("utf-8")).hexdigest(), scene.scene_sha256):
            raise PrivateScenePacketError("SCENE_HASH_MISMATCH")
        intersections = _scene_intersections(scene.start, scene.end, manifest.excerpts)
        if not intersections or intersections[0].source_start != scene.start or intersections[-1].source_end != scene.end:
            raise PrivateScenePacketError("SCENE_COVERAGE_FAILED")
        if any(intersections[i].source_end != intersections[i + 1].source_start
               for i in range(len(intersections) - 1)):
            raise PrivateScenePacketError("SCENE_COVERAGE_FAILED")
        prepared.append(PreparedScene(
            start=scene.start, end=scene.end, intersections=intersections,
            scene_id=scene.scene_id, scene_sha256=scene.scene_sha256,
            text=piece,
        ))
        prior_start, prior_end = scene.start, scene.end
    if prior_end < len(text):
        gaps.append((prior_end, len(text)))
    if gaps and not allow_gaps:
        raise PrivateScenePacketError("SCENE_GAP")

    return ScenePacket(
        source_chars=len(text), excerpt_count=len(manifest.excerpts),
        coverage="PARTIAL_EXPLICIT_GAPS" if gaps else "EXACT_SCENE_COVERAGE",
        offset_unit="unicode_code_points", gaps=tuple(gaps),
        source_record=manifest.source_record, scenes=tuple(prepared),
    )
