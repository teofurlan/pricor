"""Minimal Ollama chat client over `urllib` (no third-party dependencies).

It asks for structured output (`format` = JSON schema), `temperature` 0 and no
streaming, and returns the parsed JSON object. The transport is injectable so
tests never touch the network. Everything the model says is untrusted: this
module only parses it, the adapters validate it.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelTimeoutError,
    ModelUnavailableError,
)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:e4b"
DEFAULT_TIMEOUT_SECONDS = 180.0
_MAX_RESPONSE_BYTES = 4_000_000

# (url, request body, timeout seconds) -> raw response body
Transport = Callable[[str, bytes, float], bytes]


def urllib_transport(url: str, body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read(_MAX_RESPONSE_BYTES)


@dataclass(frozen=True)
class ChatReply:
    content: dict[str, Any]
    latency_seconds: float


class OllamaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Transport = urllib_transport,
        think: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._transport = transport
        # Gemma 4 can reason before answering; structured extraction does not need it.
        self.think = think

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> ChatReply:
        """Send one chat turn and return the JSON object the model produced."""
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "think": self.think,
                "format": schema,
                "options": {"temperature": 0},
            }
        ).encode()
        started = time.perf_counter()
        raw = self._send(f"{self.base_url}/api/chat", body)
        latency = time.perf_counter() - started
        return ChatReply(self._parse(raw), latency)

    def _send(self, url: str, body: bytes) -> bytes:
        try:
            return self._transport(url, body, self.timeout)
        except TimeoutError as error:
            raise ModelTimeoutError(f"the model did not answer within {self.timeout:g}s") from error
        except urllib.error.HTTPError as error:
            raise ModelUnavailableError(
                f"the model server answered HTTP {error.code}: {error.reason}"
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError(
                    f"the model did not answer within {self.timeout:g}s"
                ) from error
            raise ModelUnavailableError(
                f"cannot reach the model server at {self.base_url}: {error.reason}"
            ) from error
        except OSError as error:
            raise ModelUnavailableError(
                f"cannot reach the model server at {self.base_url}: {error}"
            ) from error

    @staticmethod
    def _parse(raw: bytes) -> dict[str, Any]:
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise ModelInvalidJsonError("the model server reply is not JSON") from error
        message = envelope.get("message") if isinstance(envelope, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ModelInvalidJsonError("the model server reply has no message content")
        try:
            parsed = json.loads(content)
        except ValueError as error:
            raise ModelInvalidJsonError("the model answer is not valid JSON") from error
        if not isinstance(parsed, dict):
            raise ModelInvalidJsonError("the model answer is JSON but not an object")
        return parsed
