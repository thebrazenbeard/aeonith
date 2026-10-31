"""One-command manuscript-to-critique workflow.

Usage:

    python -m aeonith.workflow --input draft.md
    python -m aeonith.workflow --input draft.md --provider openai-responses \
        --url https://api.openai.com/v1/responses --model SELECTED_MODEL \
        --allow-external-disclosure --output review.md

Nothing invokes a model unless the provider is explicitly selected. For a
non-loopback endpoint, the caller must also explicitly acknowledge disclosure.
That acknowledgment is NOT authenticated consent, an endpoint allowlist, cost
control, provider-side retention assurance, or host authorization.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlsplit
from typing import Any

from .core import CANONICAL_LENSES, critique
from .formatting import EXIT_CODES, render_review_markdown
from .providers import OpenAICompatibleProvider, OpenAIResponsesProvider
from .text_input import MAX_OUTPUT_BYTES, TextInputError, _read_text, make_request


LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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
    parser.add_argument("--provider", choices=("none", "openai-compatible", "openai-responses"),
                        default="none", help="model calls are opt-in; defaults to unavailable")
    parser.add_argument("--url", help="full model endpoint URL")
    parser.add_argument("--model", help="model identifier supported by the selected provider")
    parser.add_argument("--api-key-env", default="AEONITH_PROVIDER_API_KEY",
                        help="environment variable name for a required key, never its value")
    parser.add_argument("--allow-external-disclosure", action="store_true",
                        help="acknowledge that the whole manuscript may be transmitted to a nonlocal provider")
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--token-field", choices=("max_tokens", "max_completion_tokens", "none"),
                        default="max_tokens")
    parser.add_argument("--omit-temperature", action="store_true")
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument("--json-mode", action="store_true",
                         help="request compatible Chat Completions JSON mode")
    formats.add_argument("--no-json-mode", action="store_true",
                         help="disable default Responses JSON mode for a compatible endpoint")
    parser.add_argument("--structured-outputs", action="store_true",
                        help="request strict JSON Schema output from a compatible provider/model")
    return parser


def _build_provider(args: argparse.Namespace) -> Any:
    if args.provider == "none":
        return None
    url = args.url or ""
    model = args.model or ""
    # Validate locally before deciding which destination needs disclosure.
    # Provider constructors do not connect; critique() is the only call site.
    common = {
        "url": url,
        "model": model,
        "api_key": os.environ.get(args.api_key_env),
        "max_tokens": args.max_output_tokens,
    }
    if args.provider == "openai-compatible":
        return OpenAICompatibleProvider(
            **common,
            token_field=args.token_field,
            temperature=None if args.omit_temperature else 0.2,
            json_mode=args.json_mode,
            structured_outputs=args.structured_outputs,
        )
    return OpenAIResponsesProvider(
        **common, json_mode=not args.no_json_mode,
        structured_outputs=args.structured_outputs,
    )


def _external_disclosure_required(args: argparse.Namespace) -> bool:
    if args.provider == "none":
        return False
    url = args.url or ""
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return False
    # A missing or malformed host never reaches a model call: provider
    # constructors reject it as invalid configuration before review().
    if hostname is None:
        return False
    return hostname not in LOCAL_HOSTS


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
    if args.provider != "none":
        # Bind the selected destination once. Consent gating and the eventual
        # provider constructor must inspect exactly the same endpoint value.
        args.url = args.url or os.environ.get("AEONITH_PROVIDER_URL", "")
        args.model = args.model or os.environ.get("AEONITH_PROVIDER_MODEL", "")
    if _external_disclosure_required(args) and not args.allow_external_disclosure:
        print(
            "External model disclosure blocked: review the provider's privacy terms and "
            "use --allow-external-disclosure to acknowledge manuscript transmission.",
            file=sys.stderr,
        )
        return 2
    try:
        provider = _build_provider(args)
        request = _load_request(args)
    except (OSError, ValueError, UnicodeError):
        print("Could not prepare Aeonith critique: invalid manuscript or provider configuration",
              file=sys.stderr)
        return 2

    # Reserve a unique owner-readable output BEFORE invoking a possibly paid
    # provider. If the path exists, no manuscript is transmitted and no model
    # call occurs. This is a local convenience, not a billing or quota guard.
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
