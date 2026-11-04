"""Bounded, non-sensitive qualification of an explicitly selected local model.

This exercises the real Aeonith review and structural-audit path. It never
returns literary text, generated critique prose, HTTP URLs, bearer tokens, or
provider exception messages. A successful result is NOT a literary-quality pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

from aeonith import critique
from aeonith.core import CANONICAL_LENSES
from aeonith.private_output import PrivateOutputError, reserve_private_file
from aeonith.providers import LocalOpenAICompatibleProvider
from evaluation.quality_eval import audit_review


PILOT_SCHEMA = "aeonith.local_model_pilot.v1"
CASES = (
    {
        "id": "mirror-at-dusk",
        "title": "The Mirror",
        "text": "At dusk, the watchmaker returned the mirror. 'It shows tomorrow,' she said, "
                "but the glass held yesterday's rain.",
    },
    {
        "id": "unanswered-bell",
        "title": "The Bell",
        "text": "Twice the bell rang beneath the bridge. Neri waited for a third sound; "
                "the river carried only the first two home.",
    },
    {
        "id": "thin-fragment",
        "title": "The Threshold",
        "text": "The last door stayed open.",
    },
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _check_inputs(model: str, repeats: int, lenses: tuple[str, ...],
                  cases: tuple[dict[str, str], ...]) -> None:
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError("model identifier must be 1..200 characters")
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("repeats must be an integer between 1 and 10")
    if not lenses or len(set(lenses)) != len(lenses) or any(
        not isinstance(lens, str) or lens not in CANONICAL_LENSES for lens in lenses
    ):
        raise ValueError("lenses must be distinct canonical identifiers")
    if not 1 <= len(cases) <= len(CASES):
        raise ValueError("select between one and three cases")
    if any(not isinstance(case, dict) or set(case) != {"id", "title", "text"}
           or any(not isinstance(case[key], str) for key in ("id", "title", "text"))
           or not case["text"].strip() or len(case["text"]) > 5_000
           or case not in CASES
           for case in cases):
        raise ValueError("only registered original pilot cases are accepted")


def run_pilot(provider: Any, *, model: str, repeats: int = 1,
              lenses: Iterable[str] = ("symbolic",),
              cases: Iterable[dict[str, str]] = (CASES[0],)) -> dict[str, Any]:
    """Execute every requested attempt, retaining only sanitized observations.

    `provider` is injectable for deterministic testing. The CLI constructs only
    `LocalOpenAICompatibleProvider`, which rejects remote endpoints and keys.
    """
    selected_lenses = tuple(lenses)
    selected_cases = tuple(cases)
    _check_inputs(model, repeats, selected_lenses, selected_cases)
    attempts: list[dict[str, Any]] = []

    for case in selected_cases:
        request = {
            "schema_version": "aeonith.review.v1",
            "work": {"title": case["title"], "text": case["text"]},
            "lenses": list(selected_lenses),
        }
        for trial in range(1, repeats + 1):
            start = time.perf_counter()
            try:
                result = critique(request, provider=provider)
            except Exception:
                # Intentionally withhold exception type and message; custom
                # providers could include manuscript text or bearer secrets.
                result = {"status": "runner_error"}
            elapsed = round(max(0.0, time.perf_counter() - start), 3)
            status = result.get("status")
            if status not in {
                "completed", "provider_unavailable", "provider_error",
                "invalid_provider_output", "invalid_request", "runner_error",
            }:
                status = "runner_error"
            outcome: dict[str, Any] = {
                "case_id": case["id"],
                "case_sha256": _sha256(case["text"]),
                "repeat": trial,
                "elapsed_seconds": elapsed,
                "status": status,
                "structural_status": "not_evaluable",
                "quote_supported_lenses": 0,
                "lens_outcomes": [],
                "audit_violations": [],
                "audit_warnings": [],
            }
            if status == "completed":
                try:
                    audit = audit_review(request, result)
                    outcome["structural_status"] = audit["structural_status"]
                    outcome["audit_violations"] = [
                        item["code"] for item in audit["violations"]
                    ]
                    outcome["audit_warnings"] = [
                        item["code"] for item in audit["warnings"]
                    ]
                    for row in result["lens_reviews"]:
                        work_quotes = sum(
                            1 for anchor in row["support"] if anchor["source"] == "work"
                        )
                        outcome["quote_supported_lenses"] += bool(work_quotes)
                        outcome["lens_outcomes"].append({
                            "lens": row["lens"],
                            "basis": row["basis"],
                            "work_quote_count": work_quotes,
                            "limitation_count": len(row["limitations"]),
                        })
                except Exception:
                    # Even an unexpected audit failure must not echo the
                    # model output or pretend to establish correctness.
                    outcome["structural_status"] = "fail"
                    outcome["audit_violations"] = ["audit_exception"]
                    outcome["quote_supported_lenses"] = 0
                    outcome["lens_outcomes"] = []
            attempts.append(outcome)

    completed = sum(row["status"] == "completed" for row in attempts)
    structural_pass = sum(row["structural_status"] == "pass" for row in attempts)
    structural_fail = sum(row["structural_status"] == "fail" for row in attempts)
    return {
        "schema_version": PILOT_SCHEMA,
        "model_identifier_sha256": _sha256(model),
        "transport": "explicit_uncredentialed_loopback_chat",
        "selected_lenses": list(selected_lenses),
        "semantic_quality": "UNASSESSED",
        "human_evaluation": "NOT_PERFORMED",
        "summary": {
            "attempts": len(attempts),
            "completed": completed,
            "structural_pass": structural_pass,
            "structural_fail": structural_fail,
            "provider_or_model_failures": len(attempts) - completed,
        },
        "attempts": attempts,
    }


def _write_report_fd(fd: int, report: dict[str, Any]) -> None:
    """Write sanitized JSON through an already reserved, privately pinned fd."""
    encoded = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
               + "\n").encode("utf-8")
    view = memoryview(encoded)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("private report write did not progress")
        view = view[written:]
    os.fsync(fd)


def write_report_exclusive(path: Path, report: dict[str, Any]) -> None:
    """Write only through the qualified private output boundary, never in Git."""
    fd = reserve_private_file(path)
    try:
        _write_report_fd(fd, report)
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a sanitized, $0 local-model structural pilot; not a literary quality evaluation."
    )
    parser.add_argument("--model", required=True, help="Exact local runner model ID (not stored in report)")
    parser.add_argument("--url", default="http://127.0.0.1:5001/v1/chat/completions",
                        help="Strict numeric loopback chat endpoint only")
    parser.add_argument("--repeats", type=int, default=1, help="Attempts per case (1..10)")
    parser.add_argument("--lens", choices=CANONICAL_LENSES, action="append",
                        help="Repeat for additional lenses; default: symbolic")
    parser.add_argument("--case", choices=[case["id"] for case in CASES],
                        default=CASES[0]["id"], help="Bundled original harmless passage")
    parser.add_argument("--all-cases", action="store_true", help="Run all three original passages")
    parser.add_argument("--timeout", type=float, default=120,
                        help="Per-model-call timeout in seconds (1..600)")
    parser.add_argument("--max-tokens", type=int, default=2_048,
                        help="Maximum model output tokens (128..8192)")
    parser.add_argument("--temperature", type=float, default=0.2,
                        help="Generation temperature (0..2)")
    parser.add_argument("--structured-outputs", action="store_true",
                        help="Request JSON Schema rather than basic JSON mode")
    parser.add_argument("--output", type=Path,
                        help="Create owner-only JSON report; refuses existing target")
    args = parser.parse_args(argv)
    if not 128 <= args.max_tokens <= 8_192 or not 1 <= args.timeout <= 600:
        parser.error("model limits are outside permitted pilot bounds")
    try:
        provider = LocalOpenAICompatibleProvider(
            url=args.url, model=args.model, timeout=args.timeout,
            max_tokens=args.max_tokens, temperature=args.temperature,
            json_mode=not args.structured_outputs,
            structured_outputs=args.structured_outputs,
        )
        cases = CASES if args.all_cases else tuple(
            case for case in CASES if case["id"] == args.case
        )
        lenses = tuple(args.lens or ["symbolic"])
        _check_inputs(args.model, args.repeats, lenses, tuple(cases))
    except ValueError:
        parser.error("invalid local-only model pilot configuration")

    # A rejected path must fail *before* incurring inference, and a real report
    # must be written through the same reserved descriptor (no path re-open).
    report_fd = None
    if args.output is not None:
        try:
            report_fd = reserve_private_file(args.output)
        except (OSError, PrivateOutputError):
            parser.error("cannot create qualified private report file; existing files are preserved")
    try:
        report = run_pilot(provider, model=args.model, repeats=args.repeats,
                           lenses=lenses, cases=cases)
        if report_fd is not None:
            _write_report_fd(report_fd, report)
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    finally:
        if report_fd is not None:
            os.close(report_fd)
    return 0 if report["summary"]["structural_pass"] == report["summary"]["attempts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
