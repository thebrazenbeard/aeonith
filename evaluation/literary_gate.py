"""Small, opt-in, zero-fee literary model comparison harness.

Planning, accounting, and blinding are offline. ``run`` is the ONLY command
which contacts a model, and it requires a separately attested owner-controlled
host plus an uncredentialed numeric loopback URL. This is a test harness, not a
model-quality certificate or a host-resource verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aeonith.core import critique
from aeonith.providers import LocalOpenAICompatibleProvider
from evaluation.quality_eval import (
    _read_json, _write_json_exclusive, audit_review, build_blind_pair, digest,
)

PLAN_SCHEMA = "aeonith.literary_gate_plan.v1"
JOURNAL_SCHEMA = "aeonith.literary_gate_journal.v1"
ACCOUNTING_SCHEMA = "aeonith.literary_gate_accounting.v1"
PACKETS_SCHEMA = "aeonith.literary_gate_displays.v1"
KEYS_SCHEMA = "aeonith.literary_gate_keys.v1"
GATE_DOCUMENT = Path(__file__).resolve().parent.parent / "docs" / "LITERARY_QUALITY_GATE.md"
CASE_IDS = tuple(f"R{i:02d}-{s}" for i in range(1, 5) for s in ("N", "P")) + tuple(
    f"S{i:02d}" for i in range(1, 11)
)
CASE_LINE = re.compile(r"^\*\*((?:R0[1-4]-[NP]|S(?:0[1-9]|10))) — (.+)\*\*$")
LANES = {
    "production": {"timeout_seconds": 50, "max_output_tokens": 800,
                   "structured_outputs": False},
    "laboratory": {"timeout_seconds": 150, "max_output_tokens": 2048,
                   "structured_outputs": True},
}
MAX_JOURNAL_BYTES = 64_000_000


def load_cases(path: Path = GATE_DOCUMENT) -> list[dict[str, str]]:
    """Extract *only* the frozen 18 original fixture lines; refuse drift."""
    lines = path.read_text(encoding="utf-8").splitlines()
    cases: dict[str, dict[str, str]] = {}
    for index, line in enumerate(lines):
        match = CASE_LINE.fullmatch(line)
        if match is None:
            continue
        case_id, title = match.groups()
        if case_id in cases or not title.strip():
            raise ValueError("duplicate/empty literary challenge case")
        quote = next((candidate[2:] for candidate in lines[index + 1:index + 6]
                      if candidate.startswith("> ")), None)
        if quote is None or not quote.strip() or len(quote) > 2000:
            raise ValueError("literary challenge case has missing/oversize text")
        cases[case_id] = {"id": case_id, "title": title, "text": quote}
    if set(cases) != set(CASE_IDS) or len(cases) != len(CASE_IDS):
        raise ValueError("literary challenge set must contain exactly 18 known cases")
    return [cases[case_id] for case_id in CASE_IDS]


def make_plan(candidates: list[str], phase: str, *, cases: list[dict[str, str]] | None = None) -> dict[str, Any]:
    if (len(candidates) != 2 or len(set(candidates)) != 2
            or any(not isinstance(x, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", x)
                   for x in candidates)):
        raise ValueError("exactly two distinct short candidate IDs are required")
    if phase not in {"screen", "full"}:
        raise ValueError("phase must be screen or full")
    canonical_cases = load_cases() if cases is None else cases
    if not isinstance(canonical_cases, list) or [x.get("id") for x in canonical_cases] != list(CASE_IDS):
        raise ValueError("invalid canonical fixture set")
    chosen = [c for c in canonical_cases if phase == "full" or c["id"] in {"R01-N", "R01-P", "S01"}]
    repeats = 3 if phase == "full" else 2
    return {
        "schema_version": PLAN_SCHEMA, "phase": phase,
        "cases": chosen, "case_set_sha256": digest(canonical_cases),
        "candidates": sorted(candidates), "repeats_per_case": repeats,
        "lanes": LANES,
        "attempts": [{"candidate": candidate, "case_id": case["id"], "repeat": repeat}
                     for case in chosen for candidate in sorted(candidates)
                     for repeat in range(1, repeats + 1)],
        "provenance_status": "SOURCE_FIXTURES_AND_CALLER_DECLARED_CANDIDATES",
    }


def _validated_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or set(plan) != {
        "schema_version", "phase", "cases", "case_set_sha256", "candidates",
        "repeats_per_case", "lanes", "attempts", "provenance_status",
    } or plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("invalid literary gate plan schema")
    expected = make_plan(plan["candidates"], plan["phase"])
    if plan != expected:
        raise ValueError("literary gate plan differs from current immutable fixtures/protocol")


def _request(case: dict[str, str]) -> dict[str, Any]:
    return {"schema_version": "aeonith.review.v1",
            "work": {"title": case["title"], "text": case["text"]},
            "lenses": ["symbolic"]}


def _append_line(handle: Any, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def run_candidate(plan: dict[str, Any], candidate: str, *, provider: Any, model: str,
                  lane: str, journal_path: str) -> None:
    """Record every attempt, even provider failures, in a private append journal.

    A crash leaves missing slots; accounting explicitly marks them incomplete.
    Opening output exclusively before the first invocation prevents overwrite.
    """
    _validated_plan(plan)
    if candidate not in plan["candidates"] or lane not in LANES:
        raise ValueError("unknown candidate or lane")
    if not isinstance(model, str) or not model.strip() or len(model) > 300:
        raise ValueError("model identity is required")
    fd = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as journal:
        _append_line(journal, {
            "schema_version": JOURNAL_SCHEMA, "plan_sha256": digest(plan),
            "candidate": candidate, "lane": lane, "model": model,
            "host_preflight": "OPERATOR_ATTESTED_NOT_INDEPENDENTLY_VERIFIED",
            "runner": "aeonith.core.critique", "semantic_quality": "UNASSESSED",
        })
        by_id = {case["id"]: case for case in plan["cases"]}
        for attempt in plan["attempts"]:
            if attempt["candidate"] != candidate:
                continue
            request = _request(by_id[attempt["case_id"]])
            # Persist a started receipt *before* contacting the model. A host
            # failure during inference must not be mislabeled never-attempted.
            _append_line(journal, {
                "event": "attempt_started", "attempt": attempt,
                "request_sha256": digest(request),
            })
            started = time.monotonic()
            review = critique(request, provider)
            duration = time.monotonic() - started
            audit = audit_review(request, review)
            _append_line(journal, {
                "event": "attempt_finished", "attempt": attempt,
                "request_sha256": digest(request),
                "elapsed_seconds": round(duration, 3), "review": review,
                "audit": audit, "status": review["status"],
            })


def load_journal(path: str, plan: dict[str, Any]) -> tuple[dict[str, Any], dict[tuple[str, str, int], dict[str, Any]]]:
    _validated_plan(plan)
    target = Path(path)
    if target.stat().st_size > MAX_JOURNAL_BYTES:
        raise ValueError("attempt journal exceeds maximum size")
    rows = target.read_text(encoding="utf-8").splitlines(keepends=True)
    if not rows or any(not row.endswith("\n") for row in rows):
        raise ValueError("attempt journal is empty/truncated")
    # Strictly reject duplicate keys and non-finite numbers, as quality_eval does.
    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate JSON property in attempt journal")
            obj[key] = value
        return obj

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite JSON value in journal")

    entries = [json.loads(row, object_pairs_hook=unique_pairs,
                          parse_constant=reject_constant) for row in rows]
    header = entries[0]
    if (not isinstance(header, dict) or header.get("schema_version") != JOURNAL_SCHEMA
            or header.get("plan_sha256") != digest(plan)
            or header.get("candidate") not in plan["candidates"]
            or header.get("lane") not in LANES):
        raise ValueError("attempt journal does not match this plan/lane")
    valid_slots = {(a["candidate"], a["case_id"], a["repeat"]) for a in plan["attempts"]}
    records: dict[tuple[str, str, int], dict[str, Any]] = {}
    cases = {case["id"]: case for case in plan["cases"]}
    for row in entries[1:]:
        if not isinstance(row, dict) or not isinstance(row.get("attempt"), dict):
            raise ValueError("invalid attempt entry")
        attempt = row["attempt"]
        if set(attempt) != {"candidate", "case_id", "repeat"}:
            raise ValueError("invalid attempt identity")
        slot = (attempt["candidate"], attempt["case_id"], attempt["repeat"])
        if slot not in valid_slots or attempt["candidate"] != header["candidate"]:
            raise ValueError("unexpected attempt entry")
        if row.get("request_sha256") != digest(_request(cases[attempt["case_id"]])):
            raise ValueError("attempt request hash mismatch")
        if row.get("event") == "attempt_started":
            if slot in records:
                raise ValueError("duplicate attempt start")
            records[slot] = row
            continue
        if row.get("event") != "attempt_finished" or slot not in records:
            raise ValueError("finish without a prior attempt start")
        if records[slot].get("event") == "attempt_finished":
            raise ValueError("duplicate attempt finish")
        review = row.get("review")
        if not isinstance(review, dict) or row.get("status") != review.get("status"):
            raise ValueError("attempt result/status mismatch")
        expected_audit = audit_review(_request(cases[attempt["case_id"]]), review)
        if row.get("audit") != expected_audit:
            raise ValueError("attempt structural audit differs from source")
        records[slot] = row
    return header, records


def account(plan: dict[str, Any], first_path: str, second_path: str) -> tuple[dict[str, Any], dict[tuple[str, str, int], dict[str, Any]]]:
    _validated_plan(plan)
    first, a = load_journal(first_path, plan)
    second, b = load_journal(second_path, plan)
    if first["candidate"] == second["candidate"] or first["lane"] != second["lane"]:
        raise ValueError("comparisons require two distinct candidates in the same lane")
    records = {**a, **b}
    statuses = {}
    for candidate in plan["candidates"]:
        counts = {"structural_pass": 0, "structural_fail": 0,
                  "provider_noncompletion": 0, "interrupted": 0,
                  "not_attempted": 0}
        for attempt in plan["attempts"]:
            if attempt["candidate"] != candidate:
                continue
            slot = (candidate, attempt["case_id"], attempt["repeat"])
            row = records.get(slot)
            if row is None:
                counts["not_attempted"] += 1
            elif row["event"] == "attempt_started":
                counts["interrupted"] += 1
            elif row["audit"]["structural_status"] == "pass":
                counts["structural_pass"] += 1
            elif row["audit"]["structural_status"] == "fail":
                counts["structural_fail"] += 1
            else:
                counts["provider_noncompletion"] += 1
        counts["denominator"] = sum(counts.values())
        statuses[candidate] = counts
    eligible = sum(
        1 for case in plan["cases"] for repeat in range(1, plan["repeats_per_case"] + 1)
        if all((candidate, case["id"], repeat) in records and
               records[(candidate, case["id"], repeat)].get("event") == "attempt_finished" and
               records[(candidate, case["id"], repeat)]["audit"]["structural_status"] == "pass"
               for candidate in plan["candidates"])
    )
    total_pairs = len(plan["cases"]) * plan["repeats_per_case"]
    return {
        "schema_version": ACCOUNTING_SCHEMA, "plan_sha256": digest(plan),
        "lane": first["lane"], "phase": plan["phase"],
        "case_units": len(plan["cases"]), "attempts_expected": len(plan["attempts"]),
        "candidates": statuses, "blinded_pairs_eligible": eligible,
        "blinded_pairs_total": total_pairs, "semantic_quality": "UNASSESSED",
        "note": "Failures and missing attempts remain in the denominator; no human preference has been measured.",
    }, records


def make_packets(plan: dict[str, Any], first_path: str, second_path: str,
                 *, seed: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    accounting, records = account(plan, first_path, second_path)
    if not isinstance(seed, str) or not seed:
        raise ValueError("blinding seed is required")
    by_id = {case["id"]: case for case in plan["cases"]}
    displays, keys = [], []
    for case in plan["cases"]:
        for repeat in range(1, plan["repeats_per_case"] + 1):
            slots = [(candidate, case["id"], repeat) for candidate in plan["candidates"]]
            if any(slot not in records or records[slot].get("event") != "attempt_finished"
                   or records[slot]["audit"]["structural_status"] != "pass"
                   for slot in slots):
                continue
            display, key = build_blind_pair(
                _request(by_id[case["id"]]),
                records[slots[0]]["review"], records[slots[1]]["review"],
                slots[0][0], slots[1][0], seed=f"{seed}:{case['id']}:{repeat}",
            )
            # Identical model output on repeated trials otherwise produces
            # identical content-derived pair IDs. The human-study aggregator
            # correctly refuses duplicate IDs: bind each observed *attempt
            # instance* to its own reproducible pair identifier as well.
            # Keep matching A/B display+private key IDs, preserving the
            # content hashes in the key for later independent reconciliation.
            instance_id = digest({
                "source_pair_id": display["pair_id"], "plan_sha256": digest(plan),
                "case_id": case["id"], "repeat": repeat,
            })[:24]
            display["pair_id"] = instance_id
            key["pair_id"] = instance_id
            displays.append({"case_id": case["id"], "repeat": repeat, "pair": display})
            keys.append({"case_id": case["id"], "repeat": repeat, "key": key})
    if len(displays) != accounting["blinded_pairs_eligible"]:
        raise ValueError("blind packets and accounting diverged")
    return (
        {"schema_version": PACKETS_SCHEMA, "plan_sha256": digest(plan), "pairs": displays},
        {"schema_version": KEYS_SCHEMA, "plan_sha256": digest(plan), "keys": keys},
        accounting,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="Offline frozen 12-attempt screen or 108-attempt full plan")
    plan_parser.add_argument("--candidate", action="append", required=True)
    plan_parser.add_argument("--phase", choices=("screen", "full"), default="screen")
    plan_parser.add_argument("--out", required=True)
    run = commands.add_parser("run", help="OPT-IN: inference on an owner-qualified loopback host")
    run.add_argument("--plan", required=True)
    run.add_argument("--candidate", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--url", required=True)
    run.add_argument("--lane", choices=tuple(LANES), required=True)
    run.add_argument("--host-qualified", action="store_true", required=True,
                     help="operator attests real host/model/resource rights and consent; script cannot verify")
    run.add_argument("--out", required=True, help="new private 0600 JSONL journal, never overwritten")
    summary = commands.add_parser("account", help="Offline denominator-complete attempt accounting")
    blind = commands.add_parser("blind", help="Offline blinded displays and SEPARATE private assignment keys")
    for cmd in (summary, blind):
        cmd.add_argument("--plan", required=True)
        cmd.add_argument("--first", required=True)
        cmd.add_argument("--second", required=True)
        cmd.add_argument("--out", required=True)
    blind.add_argument("--key-out", required=True)
    blind.add_argument("--seed", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            obj = make_plan(args.candidate, args.phase)
            _write_json_exclusive(args.out, obj)
            print(json.dumps({"plan_sha256": digest(obj), "attempts_expected": len(obj["attempts"])}))
        elif args.command == "run":
            plan = _read_json(args.plan)
            _validated_plan(plan)
            lane = LANES[args.lane]
            # Explicit construction ensures even a deceptive URL cannot reach a paid service.
            provider = LocalOpenAICompatibleProvider(
                url=args.url, model=args.model, timeout=lane["timeout_seconds"],
                max_tokens=lane["max_output_tokens"], temperature=0.2,
                structured_outputs=lane["structured_outputs"],
                json_mode=not lane["structured_outputs"],
            )
            run_candidate(plan, args.candidate, provider=provider, model=args.model,
                          lane=args.lane, journal_path=args.out)
            print(json.dumps({"journal_written": args.out, "candidate": args.candidate}))
        elif args.command == "account":
            accounting, _ = account(_read_json(args.plan), args.first, args.second)
            _write_json_exclusive(args.out, accounting)
            print(json.dumps({"accounting_written": args.out,
                              "attempts_expected": accounting["attempts_expected"]}))
        elif args.command == "blind":
            if Path(args.out).resolve() == Path(args.key_out).resolve():
                raise ValueError("display and private keys cannot share a file")
            if Path(args.out).exists() or Path(args.key_out).exists():
                raise FileExistsError("blind output already exists")
            displays, keys, accounting = make_packets(
                _read_json(args.plan), args.first, args.second, seed=args.seed)
            # Never make a display available without also delivering its key.
            _write_json_exclusive(args.key_out, keys)
            try:
                _write_json_exclusive(args.out, displays)
            except Exception:
                Path(args.key_out).unlink(missing_ok=True)
                raise
            print(json.dumps({"display_written": args.out, "key_written": args.key_out,
                              "pairs_eligible": accounting["blinded_pairs_eligible"],
                              "pairs_total": accounting["blinded_pairs_total"]}))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        parser.exit(2, f"literary gate error: {error}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
