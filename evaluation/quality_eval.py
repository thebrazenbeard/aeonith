"""Offline, provider-neutral evaluations of Aeonith literary critique output.

This bench audits *structure and declared textual anchors*, never literary truth.
It intentionally makes no provider calls, loads no secrets, and requires humans
to adjudicate depth, insight, fairness, and meaningful lens distinctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any


REVIEW_SCHEMA = "aeonith.review.v1"
AUDIT_SCHEMA = "aeonith.quality_audit.v1"
PAIR_SCHEMA = "aeonith.blind_pair.v1"
KEY_SCHEMA = "aeonith.blind_pair_key.v1"
ANNOTATION_SCHEMA = "aeonith.human_annotation.v1"
MANIFEST_SCHEMA = "aeonith.run_manifest.v1"
CANONICAL_LENSES = (
    "psychological", "literary_thematic", "narrative_structure",
    "character_development", "historical_cultural", "philosophical",
    "genre_specific", "stylistic", "sociological", "moral_ethical",
    "symbolic", "reader_response", "linguistic", "comparative",
)
DIMENSIONS = (
    "textual_accuracy", "lens_distinctness", "critical_depth",
    "calibration", "actionability", "synthesis",
)


def digest(value: Any) -> str:
    """Stable content hash of strictly serializable data (no generated timestamp)."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _work_text(request: dict[str, Any]) -> str:
    work = request.get("work", request.get("proposition"))
    if isinstance(work, str):
        return work
    if isinstance(work, dict) and isinstance(work.get("text"), str):
        return work["text"]
    raise ValueError("request must contain work.text (or proposition)")


def _requested_lenses(request: dict[str, Any]) -> list[str]:
    lenses = request.get("lenses", list(CANONICAL_LENSES))
    if (not isinstance(lenses, list) or not lenses
            or len(lenses) > len(CANONICAL_LENSES)
            or any(not isinstance(x, str) or x not in CANONICAL_LENSES for x in lenses)
            or len(set(lenses)) != len(lenses)):
        raise ValueError("request lenses must be distinct canonical lens names")
    return lenses


def _provided_refs(request: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    claims = request.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError("request claims must be a list")
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("evidence", []), list):
            raise ValueError("request claims/evidence have invalid shape")
        for evidence in claim.get("evidence", []):
            if not isinstance(evidence, dict) or not isinstance(evidence.get("ref"), str):
                raise ValueError("request evidence ref must be a string")
            refs.add(evidence["ref"])
    return refs


def _valid_support(item: Any, text: str, refs: set[str]) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("source") == "work":
        quote = item.get("quote")
        return (set(item) == {"source", "quote"}
                and isinstance(quote, str) and bool(quote.strip())
                and len(quote) <= 500 and quote in text)
    if item.get("source") == "provided_evidence":
        ref = item.get("ref")
        return set(item) == {"source", "ref"} and isinstance(ref, str) and ref in refs
    return False


def _template_signature(analysis: str) -> str:
    """Spot lens-name-swapped boilerplate; heuristic only, never a pass gate."""
    normalized = analysis.casefold().replace("_", " ")
    for lens in CANONICAL_LENSES:
        normalized = normalized.replace(lens.replace("_", " "), "<lens>")
    return re.sub(r"\W+", " ", normalized).strip()


def audit_review(request: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Detect structural failures and exact-quote violations, without judging insight.

    Identical lens text is a *warning*: repetition often means formulaic filler,
    but there are cases where intentional reiteration is defensible.
    """
    if not isinstance(request, dict) or not isinstance(review, dict):
        raise ValueError("request and review must be JSON objects")
    text = _work_text(request)
    if not text.strip() or len(text) > 200_000:
        raise ValueError("request work text must be nonempty and at most 200000 characters")
    lenses = _requested_lenses(request)
    refs = _provided_refs(request)
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {
        "requested_lenses": len(lenses), "observed_lenses": 0,
        "anchored_lenses": 0, "insufficient_text_lenses": 0,
        "exact_duplicate_analysis_pairs": 0,
        "lens_template_duplicate_pairs": 0,
    }
    if review.get("status") != "completed":
        return {
            "schema_version": AUDIT_SCHEMA, "structural_status": "not_evaluable",
            "semantic_quality": "UNASSESSED", "violations": [], "warnings": [],
            "metrics": metrics,
            "note": "No completed semantic critique exists; do not score a provider failure as literary quality.",
        }

    if review.get("schema_version") != REVIEW_SCHEMA:
        violations.append({"code": "schema_mismatch", "path": "schema_version"})
    if review.get("assessment") not in (None, "SURVIVES", "FAILS", "UNKNOWN"):
        violations.append({"code": "invalid_assessment", "path": "assessment"})
    rows = review.get("lens_reviews")
    if not isinstance(rows, list):
        rows = []
        violations.append({"code": "invalid_lens_reviews", "path": "lens_reviews"})
    metrics["observed_lenses"] = len(rows)
    observed: list[str] = []
    analyses: list[str] = []
    for i, row in enumerate(rows):
        path = f"lens_reviews[{i}]"
        if not isinstance(row, dict):
            violations.append({"code": "invalid_lens_review", "path": path})
            continue
        lens = row.get("lens")
        if not isinstance(lens, str) or lens not in lenses:
            violations.append({"code": "unexpected_lens", "path": path + ".lens"})
        else:
            observed.append(lens)
        analysis = row.get("analysis")
        if not isinstance(analysis, str) or not analysis.strip() or len(analysis) > 6000:
            violations.append({"code": "invalid_analysis", "path": path + ".analysis"})
        else:
            analyses.append(analysis.strip().casefold())
        basis = row.get("basis")
        if basis not in ("textual", "insufficient_text"):
            violations.append({"code": "invalid_basis", "path": path + ".basis"})
        support = row.get("support")
        if not isinstance(support, list) or len(support) > 12:
            violations.append({"code": "invalid_support", "path": path + ".support"})
            support = []
        for j, anchor in enumerate(support):
            if not _valid_support(anchor, text, refs):
                violations.append({"code": "unsupported_quote_or_ref",
                                   "path": path + f".support[{j}]"})
        limitations = row.get("limitations")
        if (not isinstance(limitations, list) or len(limitations) > 15
                or any(not isinstance(x, str) or not x.strip() or len(x) > 1000
                       for x in limitations)):
            violations.append({"code": "invalid_limitations", "path": path + ".limitations"})
            limitations = []
        if basis == "textual":
            if not support:
                violations.append({"code": "unanchored_textual_analysis", "path": path})
            elif all(_valid_support(x, text, refs) for x in support):
                metrics["anchored_lenses"] += 1
        elif basis == "insufficient_text":
            metrics["insufficient_text_lenses"] += 1
            if not limitations:
                violations.append({"code": "unexplained_insufficiency", "path": path})

    counts = Counter(observed)
    for lens in lenses:
        if counts.get(lens, 0) == 0:
            violations.append({"code": "missing_lens", "lens": lens})
        if counts.get(lens, 0) > 1:
            violations.append({"code": "duplicate_lens", "lens": lens})
    normalized = Counter(analyses)
    duplicates = sum(c * (c - 1) // 2 for c in normalized.values())
    metrics["exact_duplicate_analysis_pairs"] = duplicates
    if duplicates:
        warnings.append({"code": "repeated_analysis_heuristic",
                         "message": "Identical lens text across multiple lenses; a human must judge whether it is filler."})
    template_counts = Counter(_template_signature(analysis) for analysis in analyses)
    template_duplicates = sum(c * (c - 1) // 2 for c in template_counts.values())
    metrics["lens_template_duplicate_pairs"] = template_duplicates
    if template_duplicates and template_duplicates > duplicates:
        warnings.append({"code": "repeated_lens_template_heuristic",
                         "message": "Analysis appears copied with only lens names changed; inspect manually."})
    synthesis = review.get("synthesis")
    if not isinstance(synthesis, str) or not synthesis.strip() or len(synthesis) > 12000:
        violations.append({"code": "missing_synthesis", "path": "synthesis"})
    challenges = review.get("challenges", [])
    if not isinstance(challenges, list) or len(challenges) > 30:
        violations.append({"code": "invalid_challenges", "path": "challenges"})
    else:
        for i, challenge in enumerate(challenges):
            path = f"challenges[{i}]"
            if (not isinstance(challenge, dict) or not isinstance(challenge.get("text"), str)
                    or not challenge["text"].strip() or len(challenge["text"]) > 2000):
                violations.append({"code": "invalid_challenge", "path": path})
                continue
            anchors = challenge.get("support", [])
            if not isinstance(anchors, list) or len(anchors) > 12:
                violations.append({"code": "invalid_challenge_support", "path": path + ".support"})
            else:
                for j, anchor in enumerate(anchors):
                    if not _valid_support(anchor, text, refs):
                        violations.append({"code": "unsupported_quote_or_ref",
                                           "path": path + f".support[{j}]"})
    uncertainties = review.get("uncertainties", [])
    if (not isinstance(uncertainties, list) or len(uncertainties) > 30
            or any(not isinstance(x, str) or not x.strip() or len(x) > 1000
                   for x in uncertainties)):
        violations.append({"code": "invalid_uncertainties", "path": "uncertainties"})
    return {
        "schema_version": AUDIT_SCHEMA,
        "structural_status": "fail" if violations else "pass",
        "semantic_quality": "UNASSESSED", "violations": violations,
        "warnings": warnings, "metrics": metrics,
        "note": "Exact-match and coverage checks only. Neither pass nor fail determines artistic merit.",
    }


def _public_view(review: dict[str, Any]) -> dict[str, Any]:
    """Project validated literary fields, excluding provider/diagnostic metadata.

    This is field-level blinding, not a guarantee that free-form model prose
    lacks identity clues. Reviewers must separately inspect such disclosures.
    """
    if not isinstance(review, dict):
        raise ValueError("comparison candidates must be objects")
    rows = review.get("lens_reviews", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("candidate lens_reviews must be a list of objects")
    challenges = review.get("challenges", [])
    if not isinstance(challenges, list) or any(not isinstance(x, dict) for x in challenges):
        raise ValueError("candidate challenges must be a list of objects")

    def public_support(items: Any) -> list[dict[str, str]]:
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise ValueError("candidate support must be a list of objects")
        projected = []
        for item in items:
            source = item.get("source")
            if source == "work" and isinstance(item.get("quote"), str):
                projected.append({"source": "work", "quote": item["quote"]})
            elif source == "provided_evidence" and isinstance(item.get("ref"), str):
                projected.append({"source": "provided_evidence", "ref": item["ref"]})
            else:
                raise ValueError("candidate support source must be a literal anchor")
        return projected

    return {
        "assessment": review.get("assessment"),
        "lens_reviews": [{"lens": row.get("lens"), "analysis": row.get("analysis"),
                          "basis": row.get("basis"),
                          "support": public_support(row.get("support", [])),
                          "limitations": list(row.get("limitations", []))}
                         for row in rows],
        "synthesis": review.get("synthesis"),
        "challenges": [{"text": item.get("text"),
                        "support": public_support(item.get("support", []))}
                       for item in challenges],
        "uncertainties": list(review.get("uncertainties", [])),
    }


def build_blind_pair(request: dict[str, Any], first: dict[str, Any],
                     second: dict[str, Any], first_id: str, second_id: str,
                     *, seed: str = "aeonith-eval-v1") -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic order-swapped assignment; store key separately from annotators."""
    if not first_id or not second_id or first_id == second_id:
        raise ValueError("candidate identifiers must be different and nonempty")
    if (not all(isinstance(x, str) and len(x) <= 200 for x in (first_id, second_id))):
        raise ValueError("candidate identifiers must be short strings")
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be a nonempty string")
    _work_text(request)
    for candidate in (first, second):
        if audit_review(request, candidate)["structural_status"] != "pass":
            raise ValueError("blind comparison requires two structurally valid completed reviews")
    canonical_candidates = sorted([(first_id, first), (second_id, second)], key=lambda pair: pair[0])
    candidate_hashes = [(name, digest(candidate)) for name, candidate in canonical_candidates]
    pair_id = digest({"request": request, "candidates": candidate_hashes})[:24]
    # A fixed SHA-256 bit yields reproducible randomization without global RNG state.
    flipped = int(digest({"pair_id": pair_id, "seed": seed})[-1], 16) % 2 == 1
    labels = list(reversed(canonical_candidates)) if flipped else canonical_candidates
    submitted_work = request.get("work", request.get("proposition"))
    safe_work = {"text": _work_text(request)}
    if isinstance(submitted_work, dict):
        title = submitted_work.get("title", "")
        if not isinstance(title, str) or len(title) > 500:
            raise ValueError("work title must be a short string")
        safe_work["title"] = title
    display = {
        "schema_version": PAIR_SCHEMA, "pair_id": pair_id,
        "request": {"work": safe_work,
                    "lenses": _requested_lenses(request)},
        "A": _public_view(labels[0][1]), "B": _public_view(labels[1][1]),
        "directions": "Score both critiques independently before choosing a preference. Do not infer model identity.",
    }
    key = {
        "schema_version": KEY_SCHEMA, "pair_id": pair_id,
        "assignment": {"A": labels[0][0], "B": labels[1][0]},
        "seed_hash": digest(seed), "flipped": flipped,
        "request_hash": digest(request),
        "candidate_hashes": dict(candidate_hashes),
    }
    return display, key


def validate_annotation(annotation: dict[str, Any], pair: dict[str, Any]) -> None:
    """Raise ValueError unless a human's independent A/B rubric is complete."""
    if not isinstance(annotation, dict) or not isinstance(pair, dict):
        raise ValueError("annotation and pair must be objects")
    expected = {"schema_version", "pair_id", "reviewer_pseudonym",
                "dimensions", "preference", "rationale"}
    if set(annotation) != expected or annotation.get("schema_version") != ANNOTATION_SCHEMA:
        raise ValueError("unexpected annotation schema or fields")
    if annotation.get("pair_id") != pair.get("pair_id"):
        raise ValueError("pair_id does not match blinded comparison")
    nickname = annotation.get("reviewer_pseudonym")
    if not isinstance(nickname, str) or not nickname.strip() or len(nickname) > 80:
        raise ValueError("reviewer pseudonym must be 1..80 characters")
    dims = annotation.get("dimensions")
    if not isinstance(dims, dict) or set(dims) != set(DIMENSIONS):
        raise ValueError("all six dimension ratings are required")
    for dim, score in dims.items():
        if (not isinstance(score, dict) or set(score) != {"A", "B"}
                or any(type(score[key]) is not int or score[key] not in (0, 1, 2)
                       for key in ("A", "B"))):
            raise ValueError(f"{dim} ratings must use integer 0, 1, or 2 for A and B")
    if annotation.get("preference") not in ("A", "B", "tie", "incomparable"):
        raise ValueError("preference must be A, B, tie, or incomparable")
    rationale = annotation.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) < 20 or len(rationale) > 4000:
        raise ValueError("a substantive 20..4000 character rationale is required")


def make_manifest(request: dict[str, Any], review: dict[str, Any], *,
                  provider_id: str, model_id: str, code_revision: str,
                  prompt_revision: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Pure repeatability record; redact prompts/text by storing only digests.

    Caller-supplied metadata is unverified provenance; a hash is not evidence
    that a model, prompt, or human really produced this output.
    """
    metadata = (provider_id, model_id, code_revision, prompt_revision)
    if any(not isinstance(value, str) or not value.strip() or len(value) > 200
           for value in metadata):
        raise ValueError("all four provenance identifiers are required")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    numeric_fields = {"temperature", "top_p", "frequency_penalty", "presence_penalty"}
    count_fields = {"max_tokens", "max_input_tokens", "max_output_tokens",
                    "max_completion_tokens", "top_k", "seed"}
    enum_fields = {
        "reasoning_effort": {"none", "minimal", "low", "medium", "high", "xhigh"},
        "verbosity": {"low", "medium", "high"},
        "response_format": {"json_object", "json_schema", "text"},
        "truncation": {"disabled", "auto"},
    }
    for name, value in parameters.items():
        if name in numeric_fields:
            valid = type(value) in (int, float) and math.isfinite(value)
        elif name in count_fields:
            valid = type(value) is int and 0 <= value <= 1_000_000_000
        elif name in enum_fields:
            valid = isinstance(value, str) and value in enum_fields[name]
        elif name == "json_mode":
            valid = type(value) is bool
        else:
            raise ValueError("unsupported generation parameter name; use an explicit non-secret allowlist")
        if not valid:
            raise ValueError("invalid generation parameter type or value")
    # Verify JSON finite numbers and ensure the manifest cannot carry huge data.
    canonical = json.dumps(parameters, allow_nan=False, sort_keys=True)
    if len(canonical) > 10000:
        raise ValueError("parameter metadata too large")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "input_sha256": digest(request), "output_sha256": digest(review),
        "provider_id": provider_id, "model_id": model_id,
        "code_revision": code_revision, "prompt_revision": prompt_revision,
        "parameters": parameters,
        "provenance_status": "CALLER_DECLARED_UNVERIFIED",
        "semantic_quality": "UNASSESSED",
    }


def _read_json(path: str) -> dict[str, Any]:
    target = Path(path)
    if target.stat().st_size > 1_000_000:
        raise ValueError("evaluation JSON input may not exceed 1 MB")

    def _reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number {value!r}")

    def _finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number

    def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON field")
            obj[key] = value
        return obj

    with target.open("rb") as handle:
        raw = handle.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("evaluation JSON input may not exceed 1 MB")
    obj = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                     parse_float=_finite_float, object_pairs_hook=_pairs_unique)
    if not isinstance(obj, dict):
        raise ValueError("evaluation input must be a JSON object")
    return obj


def _write_json_exclusive(path: str, obj: dict[str, Any]) -> None:
    # Never replace existing data. Private 0600 even under a permissive umask.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Offline deterministic structural/quote audit")
    audit.add_argument("--request", required=True)
    audit.add_argument("--review", required=True)
    audit.add_argument("--fail-on-warnings", action="store_true",
                       help="Optional policy gate for heuristic warnings; may have false positives")
    blind = commands.add_parser("blind", help="Create a blinded A/B display and private key")
    blind.add_argument("--request", required=True)
    blind.add_argument("--first", required=True)
    blind.add_argument("--second", required=True)
    blind.add_argument("--first-id", required=True)
    blind.add_argument("--second-id", required=True)
    blind.add_argument("--display-out", required=True)
    blind.add_argument("--key-out", required=True)
    blind.add_argument("--seed", default="aeonith-eval-v1")
    annotation = commands.add_parser("validate-annotation", help="Check a human's completed rubric")
    annotation.add_argument("--pair", required=True)
    annotation.add_argument("--annotation", required=True)
    manifest = commands.add_parser("manifest", help="Record content hashes and caller-declared run metadata")
    manifest.add_argument("--request", required=True)
    manifest.add_argument("--review", required=True)
    manifest.add_argument("--provider-id", required=True)
    manifest.add_argument("--model-id", required=True)
    manifest.add_argument("--code-revision", required=True)
    manifest.add_argument("--prompt-revision", required=True)
    manifest.add_argument("--parameters", help="Optional JSON file with non-secret generation parameters")
    manifest.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit_review(_read_json(args.request), _read_json(args.review))
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            if result["structural_status"] == "fail":
                return 1
            if args.fail_on_warnings and result["warnings"]:
                return 3
            return 0
        if args.command == "blind":
            if Path(args.display_out).resolve() == Path(args.key_out).resolve():
                raise ValueError("blind display and private key must be different files")
            display, key = build_blind_pair(
                _read_json(args.request), _read_json(args.first),
                _read_json(args.second), args.first_id, args.second_id, seed=args.seed)
            # Avoid creating only a display or key when the other target exists.
            for target in (args.display_out, args.key_out):
                if Path(target).exists():
                    raise FileExistsError(f"output already exists: {target}")
            created_display = False
            try:
                _write_json_exclusive(args.display_out, display)
                created_display = True
                _write_json_exclusive(args.key_out, key)
            except Exception:
                if created_display:
                    Path(args.display_out).unlink(missing_ok=True)
                raise
            print(json.dumps({"pair_id": display["pair_id"],
                              "display_written": args.display_out,
                              "key_written": args.key_out}, sort_keys=True))
            return 0
        if args.command == "validate-annotation":
            validate_annotation(_read_json(args.annotation), _read_json(args.pair))
            print(json.dumps({"valid": True}, sort_keys=True))
            return 0
        if args.command == "manifest":
            parameters = _read_json(args.parameters) if args.parameters else {}
            run = make_manifest(_read_json(args.request), _read_json(args.review),
                                provider_id=args.provider_id, model_id=args.model_id,
                                code_revision=args.code_revision,
                                prompt_revision=args.prompt_revision,
                                parameters=parameters)
            _write_json_exclusive(args.out, run)
            print(json.dumps({"manifest_written": args.out,
                              "input_sha256": run["input_sha256"],
                              "output_sha256": run["output_sha256"]}, sort_keys=True))
            return 0
    except (ValueError, FileExistsError, OSError, json.JSONDecodeError) as error:
        parser.exit(2, f"evaluation error: {error}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

