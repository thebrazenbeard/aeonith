"""Private, explicit-provider CLI for bounded manuscript segment critiques.

This command never sends a manuscript to a remote or paid provider. It never
prints manuscript prose, review text, or provider exception details to a
terminal. Completed segment reviews are *not* a whole-book synthesis.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from .book_review import (
    BatchReviewError,
    review_checkpoint_plan,
    review_longform_plan,
)
from .checkpoint import CheckpointError, plan_after_checkpoint
from .core import CANONICAL_LENSES
from .longform import LongformPlanError, _read_utf8, plan_longform
from .providers import LocalOpenAICompatibleProvider

DEFAULT_CHUNK_CHARS = 2_000
MAX_CLI_CHUNK_CHARS = 12_000
DEFAULT_MAX_SEGMENTS = 8
DEFAULT_MAX_OUTPUT_TOKENS = 2_048
DEFAULT_TOTAL_SECONDS = 180.0
DEFAULT_CALL_SECONDS = 45.0


class _DeadlineProvider:
    """Limit aggregate wall time in addition to each local request timeout."""

    name = "deadline_bounded_local"

    def __init__(self, provider: LocalOpenAICompatibleProvider, seconds: float) -> None:
        self.provider = provider
        self.initial_timeout = provider.timeout
        self.deadline = time.monotonic() + seconds

    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("local model batch time budget exhausted")
        # urllib's request timeout is an upper bound for the next socket
        # operation, not an exact real-time process deadline.
        self.provider.timeout = min(self.initial_timeout, remaining)
        return self.provider.review(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aeonith-book",
        description="Run bounded, local-only excerpt critiques from a UTF-8 manuscript.",
    )
    parser.add_argument("--input", required=True, help="local UTF-8 text or Markdown file")
    parser.add_argument("--output", required=True, help="new private JSON report; never overwritten")
    parser.add_argument("--title", default="", help="optional single-line manuscript title")
    parser.add_argument("--after-marker", help="only review text strictly after this unique marker")
    parser.add_argument("--lens", action="append", choices=CANONICAL_LENSES,
                        help="critical lens, repeatable (default: symbolic only)")
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--max-segments", type=int, default=DEFAULT_MAX_SEGMENTS)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--call-timeout-seconds", type=float, default=DEFAULT_CALL_SECONDS)
    parser.add_argument("--max-total-seconds", type=float, default=DEFAULT_TOTAL_SECONDS)
    parser.add_argument("--provider", choices=("none", "local-openai-compatible"), default="none",
                        help="explicit local model opt-in; no provider is the safe default")
    parser.add_argument("--url", default="http://127.0.0.1:5001/v1/chat/completions",
                        help="numeric loopback-only OpenAI Chat Completions URL")
    parser.add_argument("--model", default="local", help="model identifier exposed by local runner")
    parser.add_argument("--no-json-mode", action="store_true")
    parser.add_argument("--structured-outputs", action="store_true")
    return parser


def _bounded_number(value: Any, low: float, high: float) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and low <= value <= high


def _private_output_path(value: str) -> None:
    """Reject private critique reports inside any discoverable Git checkout."""
    destination = Path(value).expanduser().resolve()
    for directory in destination.parents:
        marker = directory / ".git"
        if marker.is_dir() and (marker / "HEAD").is_file():
            raise ValueError("private critique output must be outside Git repositories")
        if marker.is_file():
            try:
                if marker.read_text(encoding="utf-8", errors="ignore").startswith("gitdir:"):
                    raise ValueError("private critique output must be outside Git repositories")
            except OSError:
                # A marker we cannot inspect is not permission to write there.
                raise ValueError("cannot verify private output location")


def _prepare(args: argparse.Namespace) -> tuple[str, dict[str, Any], list[str], Any]:
    if args.input == "-" or not args.output or args.output == "-":
        raise ValueError("private input and output must be named local files")
    _private_output_path(args.output)
    if (
        len(args.title) > 500 or any(c in args.title for c in ("\x00", "\r", "\n"))
        or len(args.title.splitlines()) > 1
    ):
        raise ValueError("title must be one line")
    if type(args.chunk_chars) is not int or not 32 <= args.chunk_chars <= MAX_CLI_CHUNK_CHARS:
        raise ValueError("invalid excerpt size")
    if type(args.max_segments) is not int or not 1 <= args.max_segments <= 512:
        raise ValueError("invalid segment budget")
    if type(args.max_output_tokens) is not int or not 256 <= args.max_output_tokens <= 8_192:
        raise ValueError("invalid model output limit")
    if not _bounded_number(args.call_timeout_seconds, 1, 300):
        raise ValueError("invalid local call timeout")
    if not _bounded_number(args.max_total_seconds, 1, 3_600):
        raise ValueError("invalid total time budget")
    lenses = list(args.lens) if args.lens is not None else ["symbolic"]
    if len(set(lenses)) != len(lenses):
        raise ValueError("duplicate critical lenses")

    source = _read_utf8(args.input)  # strict UTF-8, up to 8 MB
    if args.after_marker is not None:
        plan = plan_after_checkpoint(
            source, marker=args.after_marker, title=args.title,
            max_chunk_chars=args.chunk_chars,
        )
        segments = plan["excerpt_plan"]["segments"]
    else:
        plan = plan_longform(source, title=args.title, max_chunk_chars=args.chunk_chars)
        segments = plan["segments"]
    # The entire batch must fit before opening a provider or reserving output.
    if len(segments) > args.max_segments:
        raise BatchReviewError("source exceeds segment-call budget")

    provider = None
    if args.provider == "local-openai-compatible":
        local = LocalOpenAICompatibleProvider(
            url=args.url, model=args.model, max_tokens=args.max_output_tokens,
            timeout=min(args.call_timeout_seconds, args.max_total_seconds),
            json_mode=not args.no_json_mode,
            structured_outputs=args.structured_outputs,
        )
        provider = _DeadlineProvider(local, args.max_total_seconds)
    return source, plan, lenses, provider


def _run_batch(
    source: str, plan: dict[str, Any], lenses: list[str], provider: Any,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if args.after_marker is not None:
        return review_checkpoint_plan(
            source, plan, provider=provider, marker=args.after_marker,
            max_segments=args.max_segments, lenses=lenses,
        )
    return review_longform_plan(
        source, plan, provider=provider,
        max_segments=args.max_segments, lenses=lenses,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source, plan, lenses, provider = _prepare(args)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        print("Cannot prepare private manuscript batch: invalid source, model or limits",
              file=sys.stderr)
        return 2

    # Exclusive creation prevents data loss and checks occupancy *before*
    # expensive inference. On POSIX, mode 0600 denies other users access.
    reserved_fd: int | None = None
    try:
        reserved_fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        print("Cannot reserve new private output file; existing files are never overwritten",
              file=sys.stderr)
        return 2

    try:
        result = _run_batch(source, plan, lenses, provider, args)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True,
                              allow_nan=False) + "\n"
        with os.fdopen(reserved_fd, "w", encoding="utf-8") as output:
            reserved_fd = None
            output.write(rendered)
        if result["status"] == "segments_completed":
            print("Aeonith excerpt batch completed; no whole-book synthesis was generated.",
                  file=sys.stderr)
            return 0
        if result["status"] == "provider_unavailable":
            print("No model was invoked: a local provider was not enabled.", file=sys.stderr)
            return 3
        print("Aeonith batch incomplete; inspect the private report for segment statuses.",
              file=sys.stderr)
        if any(item["status"] == "invalid_provider_output" for item in result["reviews"]):
            return 5
        return 4
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        print("Could not finish private batch review; output may be empty or partial",
              file=sys.stderr)
        return 2
    finally:
        if reserved_fd is not None:
            os.close(reserved_fd)


if __name__ == "__main__":
    raise SystemExit(main())
