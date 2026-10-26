import json
import urllib.error

import pytest

from pricor.adapters.gemini_embedder import (
    DEFAULT_BASE_URL,
    DEFAULT_DIMENSIONALITY,
    DEFAULT_MODEL,
    GeminiEmbedder,
)
from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelSchemaError,
    ModelTimeoutError,
    ModelUnavailableError,
)


class FakeTransport:
    def __init__(self, reply=b'{"embeddings": [{"values": [1.0, 2.5]}, {"values": [3.0, 4.0]}]}', error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.error:
            raise self.error
        return self.reply


def test_embeds_texts_with_batch_embed_endpoint():
    transport = FakeTransport()
    embedder = GeminiEmbedder(
        api_key="secret-embed-key",
        model="gemini-embedding-001",
        output_dimensionality=768,
        timeout=15.0,
        base_url="https://generativelanguage.googleapis.com",
        transport=transport,
    )

    vectors = embedder.embed(["hello", "world"])

    assert vectors == [[1.0, 2.5], [3.0, 4.0]]
    assert embedder.model == "gemini-embedding-001@768"
    (url, headers, body, timeout), = transport.calls
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
    assert headers["x-goog-api-key"] == "secret-embed-key"
    assert "secret-embed-key" not in url
    assert timeout == 15.0
    assert body == {
        "requests": [
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": "hello"}]},
                "outputDimensionality": 768,
            },
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": "world"}]},
                "outputDimensionality": 768,
            },
        ]
    }


def test_empty_input_returns_empty_vectors_without_calling_transport():
    transport = FakeTransport()
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    assert embedder.embed([]) == []
    assert len(transport.calls) == 0


def test_defaults_match_specification():
    embedder = GeminiEmbedder(api_key="key")
    assert embedder.model == f"{DEFAULT_MODEL}@{DEFAULT_DIMENSIONALITY}"
    assert embedder.model == "gemini-embedding-001@768"
    assert embedder.output_dimensionality == DEFAULT_DIMENSIONALITY
    assert embedder.timeout == 60.0
    assert embedder.base_url == DEFAULT_BASE_URL


def test_http_429_maps_to_quota_exhausted_unavailable_error():
    error = urllib.error.HTTPError("https://api", 429, "Too Many Requests", {}, None)
    transport = FakeTransport(error=error)
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    with pytest.raises(ModelUnavailableError, match="(?i)quota"):
        embedder.embed(["test"])


def test_http_error_keeps_status_code():
    error = urllib.error.HTTPError("https://api", 500, "Internal Server Error", {}, None)
    transport = FakeTransport(error=error)
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    with pytest.raises(ModelUnavailableError, match="500"):
        embedder.embed(["test"])


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no route to host"),
        OSError("network down"),
    ],
)
def test_connection_and_os_errors_raise_model_unavailable(error):
    transport = FakeTransport(error=error)
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    with pytest.raises(ModelUnavailableError):
        embedder.embed(["test"])


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timeout"),
        urllib.error.URLError(TimeoutError("timeout")),
    ],
)
def test_timeouts_raise_model_timeout_error(error):
    transport = FakeTransport(error=error)
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    with pytest.raises(ModelTimeoutError):
        embedder.embed(["test"])


def test_non_json_reply_raises_invalid_json():
    transport = FakeTransport(reply=b"not json")
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    with pytest.raises(ModelInvalidJsonError):
        embedder.embed(["test"])


@pytest.mark.parametrize(
    "reply",
    [
        b"{}",
        b'{"embeddings": "not a list"}',
        b'{"embeddings": []}',  # expected 1
        b'{"embeddings": [{"values": []}]}',  # empty vector
        b'{"embeddings": [{"values": [1, "not-a-number"]}]}',
        b'{"embeddings": [{"values": [1.0, 2.0]}, {"values": [3.0]}]}',  # dimension mismatch
    ],
)
def test_malformed_embeddings_raise_schema_error(reply):
    transport = FakeTransport(reply=reply)
    embedder = GeminiEmbedder(api_key="key", transport=transport)

    with pytest.raises(ModelSchemaError):
        embedder.embed(["one text"])


def test_api_key_never_appears_in_repr_or_error_messages():
    secret = "secret-key-embed-999"
    embedder = GeminiEmbedder(api_key=secret)

    assert secret not in repr(embedder)
    assert secret not in str(embedder)

    error = urllib.error.HTTPError(f"https://api?key={secret}", 403, f"forbidden {secret}", {}, None)
    embedder = GeminiEmbedder(api_key=secret, transport=FakeTransport(error=error))
    with pytest.raises(ModelUnavailableError) as exc_info:
        embedder.embed(["test"])
    assert secret not in str(exc_info.value)


def test_the_model_name_cannot_change_the_request_path():
    transport = FakeTransport(b'{"embeddings": [{"values": [1.0]}]}')
    embedder = GeminiEmbedder(api_key="k", model="../x/y", transport=transport)

    embedder.embed(["hello"])

    (url, _, body, _), = transport.calls
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/..%2Fx%2Fy:batchEmbedContents"
    assert body["requests"][0]["model"] == "models/../x/y"
