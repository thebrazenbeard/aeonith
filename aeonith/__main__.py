"""Command-line entry point: python -m aeonith review --input work.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .core import critique
from .providers import OpenAICompatibleProvider, OpenAIResponsesProvider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeonith")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="critique a written work using JSON input")
    review.add_argument("--input", required=True, help="request JSON file, or - for stdin")
    review.add_argument("--provider", choices=("none", "openai-compatible", "openai-responses"), default="none")
    review.add_argument("--url", help="full provider endpoint; HTTPS or unauthenticated localhost")
    review.add_argument("--model", help="model name recognized by the configured provider")
    review.add_argument("--api-key-env", default="AEONITH_PROVIDER_API_KEY", help="environment variable containing API key")
    review.add_argument("--max-output-tokens", type=int, default=8_192, help="provider output-token budget")
    review.add_argument("--token-field", choices=("max_tokens", "max_completion_tokens", "none"), default="max_tokens", help="chat-completions token field; choose explicitly for your model")
    review.add_argument("--omit-temperature", action="store_true", help="omit chat-completions temperature for models that do not support it")
    review.add_argument("--json-mode", action="store_true", help="request chat-completions JSON mode when supported")
    review.add_argument("--no-json-mode", action="store_true", help="disable default Responses JSON mode for a compatible endpoint")
    args = parser.parse_args(argv)

    try:
        if args.input == "-":
            raw = sys.stdin.read(1_000_001)
        else:
            if Path(args.input).stat().st_size > 1_000_000:
                raise ValueError("request JSON exceeds 1 MB")
            raw = Path(args.input).read_text(encoding="utf-8")
        if len(raw) > 1_000_000:
            raise ValueError("request JSON exceeds 1 MB")
        data = json.loads(raw)
        provider = None
        if args.provider == "openai-compatible":
            provider = OpenAICompatibleProvider(
                url=args.url or os.environ.get("AEONITH_PROVIDER_URL", ""),
                model=args.model or os.environ.get("AEONITH_PROVIDER_MODEL", ""),
                api_key=os.environ.get(args.api_key_env),
                max_tokens=args.max_output_tokens,
                token_field=args.token_field,
                temperature=None if args.omit_temperature else 0.2,
                json_mode=args.json_mode,
            )
        elif args.provider == "openai-responses":
            provider = OpenAIResponsesProvider(
                url=args.url or os.environ.get("AEONITH_PROVIDER_URL", ""),
                model=args.model or os.environ.get("AEONITH_PROVIDER_MODEL", ""),
                api_key=os.environ.get(args.api_key_env),
                max_tokens=args.max_output_tokens,
                json_mode=not args.no_json_mode,
            )
        result = critique(data, provider)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "aeonith.review.v1",
            "status": "invalid_request",
            "error": {"code": "input_or_configuration_error", "message": str(exc)},
        }
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False))
    return {
        "completed": 0,
        "invalid_request": 2,
        "provider_unavailable": 3,
        "provider_error": 4,
        "invalid_provider_output": 5,
    }[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
