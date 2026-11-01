"""Command-line entry point: python -m aeonith review --input work.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import critique
from .providers import LocalOpenAICompatibleProvider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeonith")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="critique a written work using JSON input")
    review.add_argument("--input", required=True, help="request JSON file, or - for stdin")
    review.add_argument("--provider", choices=("none", "local-openai-compatible"), default="none",
                        help="model use is opt-in and restricted to a locally running model")
    review.add_argument("--url", help="uncredentialed literal loopback /v1/chat/completions URL")
    review.add_argument("--model", help="loaded local model name (default: local)")
    review.add_argument("--max-output-tokens", type=int, default=4_096, help="maximum local model output tokens")
    review.add_argument("--omit-temperature", action="store_true", help="omit chat-completions temperature for models that do not support it")
    review.add_argument("--no-json-mode", action="store_true", help="disable default chat-completions JSON mode if unsupported")
    review.add_argument("--structured-outputs", action="store_true", help="opt in to strict JSON Schema format; requires a compatible model")
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
        if args.provider == "local-openai-compatible":
            provider = LocalOpenAICompatibleProvider(
                url=args.url or "http://127.0.0.1:5001/v1/chat/completions",
                model=args.model or "local",
                max_tokens=args.max_output_tokens,
                temperature=None if args.omit_temperature else 0.2,
                json_mode=not args.no_json_mode,
                structured_outputs=args.structured_outputs,
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
