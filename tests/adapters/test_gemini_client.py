import base64
import json
import urllib.error

import pytest

from pricor.adapters.gemini_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    GeminiChatClient,
)
from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelTimeoutError,
    ModelUnavailableError,
)

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


class FakeTransport:
    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.error:
            raise self.error
        return self.reply


def gemini_reply(text: str, thought: bool = False, parts: list[dict] | None = None) -> bytes:
    if parts is not None:
        return json.dumps({"candidates": [{"content": {"parts": parts}}]}).encode()
    part = {"text": text}
    if thought:
        part["thought"] = True
    return json.dumps({"candidates": [{"content": {"parts": [part]}}]}).encode()


def test_sends_structured_request_to_gemini_endpoint_with_header_key():
    transport = FakeTransport(gemini_reply('{"answer": "ok"}'))
    client = GeminiChatClient(
        api_key="secret-key-123",
        model="gemma-4-26b-a4b-it",
        timeout=15.0,
        base_url="https://generativelanguage.googleapis.com",
        transport=transport,
    )

    reply = client.chat_json("system prompt", "user query", SCHEMA)

    (url, headers, body, timeout), = transport.calls
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemma-4-26b-a4b-it:generateContent"
    assert headers["x-goog-api-key"] == "secret-key-123"
    assert "secret-key-123" not in url
    assert timeout == 15.0
    assert body == {
        "systemInstruction": {"parts": [{"text": "system prompt"}]},
        "contents": [{"role": "user", "parts": [{"text": "user query"}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": SCHEMA,
        },
    }
    assert reply.content == {"answer": "ok"}
    assert reply.latency_seconds >= 0


def test_defaults_match_specification():
    client = GeminiChatClient(api_key="test-key")
    assert client.model == DEFAULT_MODEL
    assert client.model == "gemma-4-26b-a4b-it"
    assert client.timeout == DEFAULT_TIMEOUT_SECONDS
    assert client.timeout == 60.0
    assert client.base_url == DEFAULT_BASE_URL
    assert client.base_url == "https://generativelanguage.googleapis.com"


def test_skips_thought_parts_and_uses_last_non_thought_part():
    parts = [
        {"text": "Let me think about this...", "thought": True},
        {"text": '{"answer": "first non-thought"}'},
        {"text": "Refining thoughts...", "thought": True},
        {"text": '{"answer": "final answer"}'},
    ]
    transport = FakeTransport(gemini_reply("", parts=parts))
    client = GeminiChatClient(api_key="key", transport=transport)

    reply = client.chat_json("s", "u", SCHEMA)
    assert reply.content == {"answer": "final answer"}


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ('```json\n{"answer": "fenced"}\n```', {"answer": "fenced"}),
        ('```\n{"answer": "plain-fenced"}\n```', {"answer": "plain-fenced"}),
        ('```json\n{"answer": "fenced"}\n```\n', {"answer": "fenced"}),
        ('  ```\n{"answer": "indented"}\n```  ', {"answer": "indented"}),
    ],
)
def test_strips_wrapping_code_fence_before_parsing(raw_text, expected):
    transport = FakeTransport(gemini_reply(raw_text))
    client = GeminiChatClient(api_key="key", transport=transport)

    reply = client.chat_json("s", "u", SCHEMA)
    assert reply.content == expected


@pytest.mark.parametrize(
    "reply_body",
    [
        b"{}",
        b'{"candidates": []}',
        b'{"candidates": [{}]}',
        b'{"candidates": [{"content": {}}]}',
        b'{"candidates": [{"content": {"parts": []}}]}',
        b'{"candidates": [{"content": {"parts": [{"thought": true, "text": "only thoughts"}]}}]}',
        b'{"candidates": [{"content": {"parts": [{"text": ""}]}}]}',
        b"not json at all",
        b'{"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}',
        b'{"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}',
    ],
)
def test_invalid_or_missing_parts_are_model_invalid_json(reply_body):
    transport = FakeTransport(reply_body)
    client = GeminiChatClient(api_key="key", transport=transport)

    with pytest.raises(ModelInvalidJsonError):
        client.chat_json("s", "u", SCHEMA)


def test_http_429_maps_to_quota_exhausted_unavailable_error():
    error = urllib.error.HTTPError("https://api", 429, "Too Many Requests", {}, None)
    transport = FakeTransport(error=error)
    client = GeminiChatClient(api_key="key", transport=transport)

    with pytest.raises(ModelUnavailableError, match="(?i)quota"):
        client.chat_json("s", "u", SCHEMA)


def test_http_error_keeps_status_code():
    error = urllib.error.HTTPError("https://api", 503, "Service Unavailable", {}, None)
    transport = FakeTransport(error=error)
    client = GeminiChatClient(api_key="key", transport=transport)

    with pytest.raises(ModelUnavailableError, match="503"):
        client.chat_json("s", "u", SCHEMA)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("connection refused"),
        OSError("network is down"),
    ],
)
def test_connection_and_os_errors_are_model_unavailable(error):
    transport = FakeTransport(error=error)
    client = GeminiChatClient(api_key="key", transport=transport)

    with pytest.raises(ModelUnavailableError):
        client.chat_json("s", "u", SCHEMA)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        urllib.error.URLError(TimeoutError("timed out")),
    ],
)
def test_timeout_maps_to_model_timeout_error(error):
    transport = FakeTransport(error=error)
    client = GeminiChatClient(api_key="key", transport=transport)

    with pytest.raises(ModelTimeoutError):
        client.chat_json("s", "u", SCHEMA)


def test_api_key_never_appears_in_repr_or_error_messages():
    secret = "super-secret-key-xyz"
    client = GeminiChatClient(api_key=secret)

    assert secret not in repr(client)
    assert secret not in str(client)

    # In HTTP error
    error = urllib.error.HTTPError(f"https://api?key={secret}", 401, f"unauthorized for {secret}", {}, None)
    client = GeminiChatClient(api_key=secret, transport=FakeTransport(error=error))
    with pytest.raises(ModelUnavailableError) as exc_info:
        client.chat_json("s", "u", SCHEMA)
    assert secret not in str(exc_info.value)


def test_the_model_name_cannot_change_the_request_path():
    transport = FakeTransport(gemini_reply('{"answer": "ok"}'))
    client = GeminiChatClient(api_key="k", model="../x/y", transport=transport)

    client.chat_json("s", "u", SCHEMA)

    (url, _, _, _), = transport.calls
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/..%2Fx%2Fy:generateContent"


def test_chat_json_with_images_encodes_png_parts_and_parses_reply():
    transport = FakeTransport(gemini_reply('{"answer": "vision"}'))
    client = GeminiChatClient(api_key="secret-key", transport=transport)
    img1 = b"\x89PNG\r\n\x1a\npage1"
    img2 = b"\x89PNG\r\n\x1a\npage2"

    reply = client.chat_json_with_images("system vision", "extract rows", [img1, img2], SCHEMA)

    (_, headers, body, _), = transport.calls
    assert headers["x-goog-api-key"] == "secret-key"
    assert body["systemInstruction"] == {"parts": [{"text": "system vision"}]}
    assert body["contents"] == [
        {
            "role": "user",
            "parts": [
                {"text": "extract rows"},
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(img1).decode("ascii")}},
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(img2).decode("ascii")}},
            ],
        }
    ]
    assert body["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert reply.content == {"answer": "vision"}


def test_chat_json_with_images_propagates_typed_errors():
    client = GeminiChatClient(api_key="key", transport=FakeTransport(error=TimeoutError("timed out")))
    with pytest.raises(ModelTimeoutError):
        client.chat_json_with_images("s", "u", [b"png"], SCHEMA)

    client_bad = GeminiChatClient(api_key="key", transport=FakeTransport(b"not json"))
    with pytest.raises(ModelInvalidJsonError):
        client_bad.chat_json_with_images("s", "u", [b"png"], SCHEMA)
