import json
import urllib.error

import pytest

from pricor.adapters.ollama_embedder import OllamaEmbedder
from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelSchemaError,
    ModelTimeoutError,
    ModelUnavailableError,
)


class FakeTransport:
    def __init__(self, reply=b'{"embeddings": [[1.0, 2.5], [3, 4]]}', error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def __call__(self, url, body, timeout):
        self.calls.append((url, json.loads(body), timeout))
        if self.error:
            raise self.error
        return self.reply


def test_embeds_texts_with_the_configured_ollama_model():
    transport = FakeTransport()
    embedder = OllamaEmbedder(
        base_url="http://box:11434/", model="custom-embed", timeout=7.5, transport=transport
    )

    vectors = embedder.embed(["first", "second"])

    assert vectors == [[1.0, 2.5], [3.0, 4.0]]
    assert embedder.model == "custom-embed"
    assert transport.calls == [
        (
            "http://box:11434/api/embed",
            {"model": "custom-embed", "input": ["first", "second"]},
            7.5,
        )
    ]


def test_model_defaults_from_the_environment(monkeypatch):
    monkeypatch.setenv("PRICOR_EMBED_MODEL", "env-embed")
    embedder = OllamaEmbedder(transport=FakeTransport(b'{"embeddings": []}'))

    assert embedder.model == "env-embed"
    assert embedder.embed([]) == []


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no route"),
        ConnectionResetError("reset"),
        urllib.error.HTTPError("u", 503, "unavailable", {}, None),
    ],
)
def test_unreachable_ollama_raises_model_unavailable(error):
    with pytest.raises(ModelUnavailableError):
        OllamaEmbedder(transport=FakeTransport(error=error)).embed(["note"])


@pytest.mark.parametrize(
    "error", [TimeoutError(), urllib.error.URLError(TimeoutError("timed out"))]
)
def test_timeouts_use_the_existing_model_timeout_error(error):
    with pytest.raises(ModelTimeoutError):
        OllamaEmbedder(transport=FakeTransport(error=error)).embed(["note"])


def test_non_json_reply_uses_the_existing_invalid_json_error():
    with pytest.raises(ModelInvalidJsonError):
        OllamaEmbedder(transport=FakeTransport(b"not json")).embed(["note"])


@pytest.mark.parametrize(
    "reply",
    [
        b"[]",
        b'{"embeddings": "nope"}',
        b'{"embeddings": [[], []]}',
        b'{"embeddings": [[1, "bad"]]}',
        b'{"embeddings": [[1, 2], [3]]}',
    ],
)
def test_invalid_embedding_reply_uses_the_existing_schema_error(reply):
    with pytest.raises(ModelSchemaError):
        OllamaEmbedder(transport=FakeTransport(reply)).embed(["one", "two"])
