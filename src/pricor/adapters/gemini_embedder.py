"""Gemini embedding adapter with an injectable HTTP transport."""

import json
import math
import urllib.error
import urllib.request
from urllib.parse import quote
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pricor.ports.embedder import Embedder
from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelSchemaError,
    ModelTimeoutError,
    ModelUnavailableError,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSIONALITY = 768
DEFAULT_TIMEOUT_SECONDS = 60.0
_MAX_RESPONSE_BYTES = 16_000_000

Transport = Callable[[str, Mapping[str, str], bytes, float], bytes]


def urllib_transport(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers=dict(headers), method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read(_MAX_RESPONSE_BYTES + 1)


class GeminiEmbedder(Embedder):
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        output_dimensionality: int = DEFAULT_DIMENSIONALITY,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = DEFAULT_BASE_URL,
        transport: Transport = urllib_transport,
    ):
        self._api_key = api_key
        self._raw_model = model
        self.output_dimensionality = output_dimensionality
        self.model = f"{model}@{output_dimensionality}"
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def __repr__(self) -> str:
        return (
            f"GeminiEmbedder(model={self.model!r}, timeout={self.timeout!r}, "
            f"base_url={self.base_url!r})"
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = list(texts)
        if not inputs:
            return []
        requests = [
            {
                "model": f"models/{self._raw_model}",
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": self.output_dimensionality,
            }
            for t in inputs
        ]
        body = json.dumps({"requests": requests}).encode()
        url = f"{self.base_url}/v1beta/models/{quote(self._raw_model, safe='')}:batchEmbedContents"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        raw = self._send(url, headers, body)
        return self._parse(raw, len(inputs))

    def _sanitize(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[REDACTED]")
        return text

    def _send(self, url: str, headers: Mapping[str, str], body: bytes) -> bytes:
        try:
            return self._transport(url, headers, body, self.timeout)
        except TimeoutError as error:
            raise ModelTimeoutError(
                f"the embedding model did not answer within {self.timeout:g}s"
            ) from error
        except urllib.error.HTTPError as error:
            safe_reason = self._sanitize(str(error.reason))
            if error.code == 429:
                raise ModelUnavailableError(
                    f"the embedding model server answered HTTP 429: quota exhausted ({safe_reason})"
                ) from error
            raise ModelUnavailableError(
                f"the embedding model server answered HTTP {error.code}: {safe_reason}"
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError(
                    f"the embedding model did not answer within {self.timeout:g}s"
                ) from error
            safe_reason = self._sanitize(str(error.reason))
            raise ModelUnavailableError(
                f"cannot reach the embedding model server at {self.base_url}: {safe_reason}"
            ) from error
        except OSError as error:
            safe_err = self._sanitize(str(error))
            raise ModelUnavailableError(
                f"cannot reach the embedding model server at {self.base_url}: {safe_err}"
            ) from error

    @staticmethod
    def _parse(raw: bytes, expected: int) -> list[list[float]]:
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ModelSchemaError("the embedding model reply is larger than expected")
        try:
            envelope: Any = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise ModelInvalidJsonError("the embedding model reply is not JSON") from error
        embeddings = envelope.get("embeddings") if isinstance(envelope, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != expected:
            raise ModelSchemaError("the embedding model returned the wrong number of vectors")
        vectors: list[list[float]] = []
        dimension: int | None = None
        for item in embeddings:
            if not isinstance(item, dict):
                raise ModelSchemaError("an embedding item is not an object")
            raw_vector = item.get("values")
            if not isinstance(raw_vector, list) or not raw_vector:
                raise ModelSchemaError("the embedding model returned an empty vector")
            vector: list[float] = []
            for value in raw_vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ModelSchemaError("an embedding contains a non-numeric value")
                number = float(value)
                if not math.isfinite(number):
                    raise ModelSchemaError("an embedding contains an infinite or NaN value")
                vector.append(number)
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise ModelSchemaError("embeddings have inconsistent dimensions")
            vectors.append(vector)
        return vectors
