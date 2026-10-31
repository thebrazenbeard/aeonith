"""Turn a UTF-8 manuscript into the Aeonith v1 review request contract.

No provider calls and no manuscript persistence are performed here.  The
result can be piped into ``python -m aeonith review --input -`` once integrated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCHEMA = "aeonith.review.v1"
MAX_MANUSCRIPT_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 1_000_000
MAX_TEXT_CHARS = 200_000


class TextInputError(ValueError):
    """Input manuscript cannot be represented as a valid review request."""


def make_request(text: str, *, title: str = "") -> dict[str, object]:
    """Build a minimal Aeonith request with no fabricated provenance."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise TextInputError("manuscript must contain 1 to 200000 text characters")
    if not isinstance(title, str) or len(title) > 500:
        raise TextInputError("title must not exceed 500 characters")
    if "\x00" in text:
        raise TextInputError("manuscript cannot contain NUL characters")
    return {"schema_version": SCHEMA, "work": {"title": title, "text": text}}


def _read_text(input_path: str) -> str:
    if input_path == "-":
        raw = sys.stdin.buffer.read(MAX_MANUSCRIPT_BYTES + 1)
    else:
        path = Path(input_path)
        if path.stat().st_size > MAX_MANUSCRIPT_BYTES:
            raise TextInputError("manuscript exceeds input size limit")
        with path.open("rb") as handle:
            raw = handle.read(MAX_MANUSCRIPT_BYTES + 1)
    if len(raw) > MAX_MANUSCRIPT_BYTES:
        raise TextInputError("manuscript exceeds input size limit")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TextInputError("manuscript must use UTF-8 encoding") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeonith-text-input")
    parser.add_argument("--input", required=True, help="plain UTF-8 .txt/.md work, or - for stdin")
    parser.add_argument("--title", default="", help="optional work title; not inferred from a private filename")
    args = parser.parse_args(argv)

    try:
        request = make_request(_read_text(args.input), title=args.title)
        serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
        if len(serialized.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise TextInputError("review request exceeds CLI's 1 MB limit")
        sys.stdout.write(serialized)
    except (OSError, TextInputError, UnicodeError):
        print("Could not prepare Aeonith request: invalid UTF-8 or input limits", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
