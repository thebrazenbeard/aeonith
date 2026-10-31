"""Explicit, credential-safe HTTP adapters for model-provided critiques.

No network connection is opened until an explicitly constructed provider is
invoked. These transport adapters do not certify model-generated literary
judgments; ``aeonith.core`` retains its independent output validation.
"""

from __future__ import annotations

import json
import math
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import Any


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect refused to protect credentials and request data")


def _validate_endpoint(url: str, api_key: str | None) -> None:
    if not isinstance(url, str) or not url:
        raise ValueError("provider URL is required")
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("provider URL must be an absolute HTTP(S) URL without embedded credentials")
    if parts.scheme == "http" and (parts.hostname not in {"localhost", "127.0.0.1", "::1"} or api_key):
        raise ValueError("HTTP is allowed only for unauthenticated localhost endpoints")


def _validate_model_limits(model: str, timeout: float, max_tokens: int) -> None:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("provider model is required")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise ValueError("timeout must be between 0 and 600 seconds")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 0 < max_tokens <= 65_536:
        raise ValueError("max_tokens out of supported bounds")


def _strict_json(data: bytes | str) -> Any:
    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite model JSON value")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite model JSON value")
        return number

    return json.loads(data, parse_constant=reject_constant, parse_float=finite_float)


def _post_json(url: str, api_key: str | None, timeout: float, request_body: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        url,
        data=json.dumps(request_body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        encoded = response.read(4_000_001)
    if len(encoded) > 4_000_000:
        raise ValueError("provider response exceeded 4 MB")
    value = _strict_json(encoded)
    if not isinstance(value, dict):
        raise ValueError("provider response must be a JSON object")
    return value


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
        token_field: str = "max_tokens",
        temperature: float | None = 0.2,
        json_mode: bool = False,
    ) -> None:
        _validate_endpoint(url, api_key)
        _validate_model_limits(model, timeout, max_tokens)
        if token_field not in {"max_tokens", "max_completion_tokens", "none"}:
            raise ValueError("token_field must be max_tokens, max_completion_tokens or none")
        if temperature is not None and (
            isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2
        ):
            raise ValueError("temperature must be absent or between 0 and 2")
        if not isinstance(json_mode, bool):
            raise ValueError("json_mode must be a boolean")
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.token_field = token_field
        self.temperature = temperature
        self.json_mode = json_mode

    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": payload["instructions"]},
                {"role": "user", "content": json.dumps(payload["task"], ensure_ascii=False)},
            ],
        }
        if self.temperature is not None:
            request_body["temperature"] = self.temperature
        if self.token_field != "none":
            request_body[self.token_field] = self.max_tokens
        if self.json_mode:
            request_body["response_format"] = {"type": "json_object"}
        data = _post_json(self.url, self.api_key, self.timeout, request_body)
        if not isinstance(data.get("choices"), list) or not data["choices"]:
            raise ValueError("provider returned no choices")
        choice = data["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("provider returned a malformed assistant message")
        message = choice["message"]
        if "role" in message and message["role"] != "assistant":
            raise ValueError("provider returned a non-assistant message")
        if message.get("refusal"):
            raise ValueError("model refused critique")
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and finish_reason != "stop":
            raise ValueError("provider output did not finish as assistant text")
        if message.get("tool_calls") or message.get("function_call"):
            raise ValueError("provider attempted a tool call")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("provider did not return text content")
        candidate = _strict_json(content)
        if not isinstance(candidate, dict):
            raise ValueError("provider critique must be a JSON object")
        return candidate


class OpenAIResponsesProvider:
    """Explicit OpenAI Responses API transport; no implicit tools or retrieval.

    ``store=False`` disables server-side response-state storage; it is *not* a
    promise of zero provider data retention. Only a selected trusted endpoint
    should receive manuscript text.
    """

    name = "openai_responses"

    def __init__(
        self,
        *,
        url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 90,
        max_tokens: int = 8_192,
        json_mode: bool = True,
    ) -> None:
        _validate_endpoint(url, api_key)
        _validate_model_limits(model, timeout, max_tokens)
        if not isinstance(json_mode, bool):
            raise ValueError("json_mode must be a boolean")
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.json_mode = json_mode

    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "model": self.model,
            "instructions": payload["instructions"],
            "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload["task"], ensure_ascii=False)}]}],
            "max_output_tokens": self.max_tokens,
            "store": False,
        }
        if self.json_mode:
            request_body["text"] = {"format": {"type": "json_object"}}
        response = _post_json(self.url, self.api_key, self.timeout, request_body)
        if response.get("status") != "completed" or response.get("error"):
            raise ValueError("response did not complete successfully")
        outputs = response.get("output")
        if not isinstance(outputs, list):
            raise ValueError("response output is missing")
        parts: list[str] = []
        for item in outputs:
            if not isinstance(item, dict):
                raise ValueError("malformed response output item")
            if item.get("type") == "reasoning":
                # Internal reasoning summary is not application output.
                continue
            if item.get("type") != "message":
                # No tools were granted; mixed tool calls are protocol errors.
                raise ValueError("response contained an unexpected output item")
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                raise ValueError("malformed assistant response")
            for block in item["content"]:
                if not isinstance(block, dict):
                    raise ValueError("malformed response content")
                if block.get("type") == "refusal":
                    raise ValueError("model refused critique")
                if block.get("type") == "output_text":
                    if not isinstance(block.get("text"), str):
                        raise ValueError("malformed output text")
                    parts.append(block["text"])
        if not parts:
            raise ValueError("response contained no output text")
        candidate = _strict_json("".join(parts))
        if not isinstance(candidate, dict):
            raise ValueError("provider critique must be a JSON object")
        return candidate
