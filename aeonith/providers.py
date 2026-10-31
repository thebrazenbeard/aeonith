"""Explicit HTTP adapter for OpenAI-compatible chat-completions providers.

This adapter can target a model service chosen by the operator. It is not tied
to OpenAI's hosted service and does not silently open any network connection.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import Any


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect refused to protect credentials and request data")


class OpenAICompatibleProvider:
    """Minimal /chat/completions adapter with no third-party dependencies."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 90,
        max_tokens: int = 8_192,
    ) -> None:
        if not isinstance(url, str) or not url:
            raise ValueError("provider URL is required")
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("provider URL must be an absolute HTTP(S) URL without embedded credentials")
        if parts.scheme == "http":
            if parts.hostname not in {"localhost", "127.0.0.1", "::1"} or api_key:
                raise ValueError("HTTP is allowed only for unauthenticated localhost endpoints")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("provider model is required")
        if not 0 < timeout <= 600 or not 0 < max_tokens <= 65_536:
            raise ValueError("timeout/max_tokens out of supported bounds")
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": payload["instructions"]},
                {"role": "user", "content": json.dumps(payload["task"], ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = Request(
            self.url,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with build_opener(_NoRedirect()).open(http_request, timeout=self.timeout) as response:
            encoded = response.read(4_000_001)
        if len(encoded) > 4_000_000:
            raise ValueError("provider response exceeded 4 MB")
        data = json.loads(encoded)
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("provider did not return text content")
        return json.loads(content)
