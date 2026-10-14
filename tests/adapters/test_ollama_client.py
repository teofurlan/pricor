import json
import urllib.error

import pytest

from pricor.adapters.ollama_client import OllamaClient
from pricor.ports.model_errors import (
    ModelError,
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

    def __call__(self, url, body, timeout):
        self.calls.append((url, json.loads(body), timeout))
        if self.error:
            raise self.error
        return self.reply


def envelope(content):
    return json.dumps({"message": {"role": "assistant", "content": content}}).encode()


def client(transport, **kwargs):
    return OllamaClient(transport=transport, **kwargs)


def test_sends_a_deterministic_structured_non_streaming_chat_request():
    transport = FakeTransport(envelope('{"answer": "ok"}'))

    reply = client(transport, timeout=7.5).chat_json("system text", "user text", SCHEMA)

    (url, body, timeout), = transport.calls
    assert url == "http://localhost:11434/api/chat"
    assert body["model"] == "gemma4:e4b"
    assert body["stream"] is False
    assert body["format"] == SCHEMA
    assert body["options"]["temperature"] == 0
    assert body["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]
    assert timeout == 7.5
    assert reply.content == {"answer": "ok"}
    assert reply.latency_seconds >= 0


def test_thinking_is_off_unless_requested():
    off, on = FakeTransport(envelope("{}")), FakeTransport(envelope("{}"))

    client(off).chat_json("s", "u", SCHEMA)
    client(on, think=True).chat_json("s", "u", SCHEMA)

    assert off.calls[0][1]["think"] is False
    assert on.calls[0][1]["think"] is True


def test_base_url_and_model_are_configurable():
    transport = FakeTransport(envelope("{}"))

    client(transport, base_url="http://box:9999/", model="other:1b").chat_json("s", "u", SCHEMA)

    url, body, _ = transport.calls[0]
    assert url == "http://box:9999/api/chat"
    assert body["model"] == "other:1b"


def test_unreachable_server_is_unavailable():
    transport = FakeTransport(error=urllib.error.URLError(ConnectionRefusedError()))

    with pytest.raises(ModelUnavailableError):
        client(transport).chat_json("s", "u", SCHEMA)


def test_connection_error_is_unavailable():
    with pytest.raises(ModelUnavailableError):
        client(FakeTransport(error=ConnectionResetError())).chat_json("s", "u", SCHEMA)


def test_http_error_is_unavailable_and_keeps_the_status():
    error = urllib.error.HTTPError("u", 404, "model not found", {}, None)

    with pytest.raises(ModelUnavailableError, match="404"):
        client(FakeTransport(error=error)).chat_json("s", "u", SCHEMA)


@pytest.mark.parametrize(
    "error", [TimeoutError(), urllib.error.URLError(TimeoutError("timed out"))]
)
def test_timeouts_are_typed(error):
    with pytest.raises(ModelTimeoutError):
        client(FakeTransport(error=error)).chat_json("s", "u", SCHEMA)


@pytest.mark.parametrize(
    "reply",
    [b"not json at all", envelope("this is prose, not json"), envelope("")],
)
def test_unparseable_replies_are_invalid_json(reply):
    with pytest.raises(ModelInvalidJsonError):
        client(FakeTransport(reply)).chat_json("s", "u", SCHEMA)


@pytest.mark.parametrize("reply", [b"[]", b'{"nope": 1}', b'{"message": {"content": 5}}'])
def test_unexpected_envelope_is_invalid_json(reply):
    with pytest.raises(ModelInvalidJsonError):
        client(FakeTransport(reply)).chat_json("s", "u", SCHEMA)


def test_json_that_is_not_an_object_is_invalid():
    with pytest.raises(ModelInvalidJsonError):
        client(FakeTransport(envelope("[1, 2]"))).chat_json("s", "u", SCHEMA)


def test_all_errors_share_a_base_type():
    for error in (ModelUnavailableError, ModelTimeoutError, ModelInvalidJsonError):
        assert issubclass(error, ModelError)
