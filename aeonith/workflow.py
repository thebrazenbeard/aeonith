"""One-command manuscript-to-critique workflow.

Usage:

    python -m aeonith.workflow --input draft.md
    python -m aeonith.workflow --input draft.md --provider local-openai-compatible \
        --url http://127.0.0.1:5001/v1/chat/completions --output review.md

Nothing invokes a model unless the local provider is explicitly selected.
The CLI cannot be configured to send manuscripts to a paid or remote provider.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .core import CANONICAL_LENSES, critique
from .formatting import EXIT_CODES, render_review_markdown
from .providers import LocalOpenAICompatibleProvider
from .text_input import MAX_OUTPUT_BYTES, TextInputError, _read_text, make_request


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aeonith-critique",
        description="Prepare a UTF-8 manuscript, request an explicit model critique, and render a report.",
    )
    parser.add_argument("--input", required=True, help="UTF-8 .txt/.md manuscript or - for stdin")
    parser.add_argument("--title", default="", help="optional work title")
    parser.add_argument("--lens", action="append", choices=CANONICAL_LENSES,
                        help="repeat to select particular critical lenses (default: all fourteen)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", default="-",
                        help="new output file (never overwritten), or - for stdout")
    parser.add_argument("--provider", choices=("none", "local-openai-compatible"),
                        default="none", help="model calls are opt-in; defaults to unavailable")
    parser.add_argument("--url", help="literal loopback-only /v1/chat/completions URL")
    parser.add_argument("--model", help="local model name (default: local)")
    parser.add_argument("--max-output-tokens", type=int, default=4_096)
    parser.add_argument("--omit-temperature", action="store_true")
    parser.add_argument("--no-json-mode", action="store_true",
                        help="disable JSON mode when unsupported by the local model")
    parser.add_argument("--structured-outputs", action="store_true",
                        help="request strict JSON Schema output from a compatible provider/model")
    return parser


def _build_provider(args: argparse.Namespace) -> Any:
    if args.provider == "none":
        return None
    return LocalOpenAICompatibleProvider(
        url=args.url or "http://127.0.0.1:5001/v1/chat/completions",
        model=args.model or "local",
        max_tokens=args.max_output_tokens,
        temperature=None if args.omit_temperature else 0.2,
        json_mode=not args.no_json_mode,
        structured_outputs=args.structured_outputs,
    )


def _load_request(args: argparse.Namespace) -> dict[str, Any]:
    if any(char in args.title for char in ("\r", "\n", "\x00")) or len(args.title.splitlines()) > 1:
        raise TextInputError("work title must be on one line")
    request = make_request(_read_text(args.input), title=args.title)
    if args.lens:
        if len(set(args.lens)) != len(args.lens):
            raise TextInputError("critical lenses must not repeat")
        request["lenses"] = args.lens
    # Match the existing JSON CLI's 1 MiB request ceiling before a model call.
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise TextInputError("serialized review request exceeds 1 MB")
    return request


def _render(result: dict[str, Any], args: argparse.Namespace) -> str:
    if args.format == "markdown":
        return render_review_markdown(result, title=args.title)
    return json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        provider = _build_provider(args)
        request = _load_request(args)
    except (OSError, ValueError, UnicodeError):
        print("Could not prepare Aeonith critique: invalid manuscript or provider configuration",
              file=sys.stderr)
        return 2

    # Reserve a unique owner-readable output BEFORE invoking the local model.
    # Existing files are never overwritten, and model calls are never made
    # when the output path is already occupied.
    reserved_fd: int | None = None
    try:
        if args.output != "-":
            try:
                reserved_fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except OSError:
                print("Could not reserve a new output file; existing files are never overwritten",
                      file=sys.stderr)
                return 2
        result = critique(request, provider)
        document = _render(result, args)
        if reserved_fd is None:
            sys.stdout.write(document)
        else:
            with os.fdopen(reserved_fd, "w", encoding="utf-8") as handle:
                reserved_fd = None
                handle.write(document)
        return EXIT_CODES[result["status"]]
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        print("Could not render or write Aeonith critique result", file=sys.stderr)
        return 2
    finally:
        if reserved_fd is not None:
            os.close(reserved_fd)


if __name__ == "__main__":
    raise SystemExit(main())
