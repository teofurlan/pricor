"""Gemini chat client over `urllib` (no third-party dependencies).

Sends structured JSON requests to the Google Gemini generateContent endpoint.
The API key travels exclusively in the `x-goog-api-key` header, never in the
URL, logs, exception messages, or `repr()`.
"""

import base64
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pricor.ports.chat_client import ChatClient, ChatReply
from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelTimeoutError,
    ModelUnavailableError,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemma-4-26b-a4b-it"
DEFAULT_TIMEOUT_SECONDS = 60.0
_MAX_RESPONSE_BYTES = 4_000_000

# (url, headers, request body, timeout seconds) -> raw response body
Transport = Callable[[str, Mapping[str, str], bytes, float], bytes]


def urllib_transport(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read(_MAX_RESPONSE_BYTES)


_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def strip_code_fence(text: str) -> str:
    match = _FENCE_PATTERN.match(text)
    if match:
        return match.group(1).strip()
    return text.strip()


class GeminiChatClient(ChatClient):
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = DEFAULT_BASE_URL,
        transport: Transport = urllib_transport,
    ):
        self._api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def __repr__(self) -> str:
        return (
            f"GeminiChatClient(model={self.model!r}, timeout={self.timeout!r}, "
            f"base_url={self.base_url!r})"
        )

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> ChatReply:
        return self._generate(system, [{"text": user}], schema)

    def chat_json_with_images(
        self,
        system: str,
        user: str,
        images: Sequence[bytes],
        schema: dict[str, Any],
    ) -> ChatReply:
        parts: list[dict[str, Any]] = [{"text": user}]
        for image in images:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": base64.b64encode(image).decode("ascii"),
                    }
                }
            )
        return self._generate(system, parts, schema)

    def _generate(
        self, system: str, parts: list[dict[str, Any]], schema: dict[str, Any]
    ) -> ChatReply:
        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            }
        ).encode()
        url = f"{self.base_url}/v1beta/models/{quote(self.model, safe='')}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        started = time.perf_counter()
        raw = self._send(url, headers, body)
        latency = time.perf_counter() - started
        return ChatReply(self._parse(raw), latency)

    def _sanitize(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[REDACTED]")
        return text

    def _send(self, url: str, headers: Mapping[str, str], body: bytes) -> bytes:
        try:
            return self._transport(url, headers, body, self.timeout)
        except TimeoutError as error:
            raise ModelTimeoutError(
                f"the model did not answer within {self.timeout:g}s"
            ) from error
        except urllib.error.HTTPError as error:
            safe_reason = self._sanitize(str(error.reason))
            if error.code == 429:
                raise ModelUnavailableError(
                    f"the model server answered HTTP 429: quota exhausted ({safe_reason})"
                ) from error
            raise ModelUnavailableError(
                f"the model server answered HTTP {error.code}: {safe_reason}"
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError(
                    f"the model did not answer within {self.timeout:g}s"
                ) from error
            safe_reason = self._sanitize(str(error.reason))
            raise ModelUnavailableError(
                f"cannot reach the model server at {self.base_url}: {safe_reason}"
            ) from error
        except OSError as error:
            safe_err = self._sanitize(str(error))
            raise ModelUnavailableError(
                f"cannot reach the model server at {self.base_url}: {safe_err}"
            ) from error

    @staticmethod
    def _parse(raw: bytes) -> dict[str, Any]:
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise ModelInvalidJsonError("the model server reply is not JSON") from error
        if not isinstance(envelope, dict):
            raise ModelInvalidJsonError("the model server reply is not an object")

        candidates = envelope.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ModelInvalidJsonError("the model server reply has no candidates")

        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ModelInvalidJsonError("the candidate is not an object")

        content = candidate.get("content")
        if not isinstance(content, dict):
            raise ModelInvalidJsonError("the candidate has no content object")

        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ModelInvalidJsonError("the candidate content has no parts")

        # Use the last part that is not marked "thought": true
        non_thought_parts = [
            part for part in parts
            if isinstance(part, dict) and not part.get("thought", False)
        ]
        if not non_thought_parts:
            raise ModelInvalidJsonError("the candidate content has no non-thought parts")

        target_part = non_thought_parts[-1]
        text = target_part.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ModelInvalidJsonError("the candidate part has no text content")

        cleaned = strip_code_fence(text)
        try:
            parsed = json.loads(cleaned)
        except ValueError as error:
            raise ModelInvalidJsonError("the model answer is not valid JSON") from error
        if not isinstance(parsed, dict):
            raise ModelInvalidJsonError("the model answer is JSON but not an object")
        return parsed
