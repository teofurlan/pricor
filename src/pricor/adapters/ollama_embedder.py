"""Ollama embedding adapter with an injectable HTTP transport."""

import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pricor.ports.model_errors import (
    ModelInvalidJsonError,
    ModelSchemaError,
    ModelTimeoutError,
    ModelUnavailableError,
)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "bge-m3"
DEFAULT_TIMEOUT_SECONDS = 180.0
_MAX_RESPONSE_BYTES = 16_000_000

Transport = Callable[[str, bytes, float], bytes]


def urllib_transport(url: str, body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read(_MAX_RESPONSE_BYTES + 1)


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Transport = urllib_transport,
        env: Mapping[str, str] | None = None,
    ):
        environment = os.environ if env is None else env
        self.base_url = base_url.rstrip("/")
        self.model = model or environment.get("PRICOR_EMBED_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self._transport = transport

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = list(texts)
        body = json.dumps({"model": self.model, "input": inputs}).encode()
        raw = self._send(f"{self.base_url}/api/embed", body)
        return self._parse(raw, len(inputs))

    def _send(self, url: str, body: bytes) -> bytes:
        try:
            return self._transport(url, body, self.timeout)
        except TimeoutError as error:
            raise ModelTimeoutError(
                f"the embedding model did not answer within {self.timeout:g}s"
            ) from error
        except urllib.error.HTTPError as error:
            raise ModelUnavailableError(
                f"the embedding model server answered HTTP {error.code}: {error.reason}"
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError(
                    f"the embedding model did not answer within {self.timeout:g}s"
                ) from error
            raise ModelUnavailableError(
                f"cannot reach the embedding model server at {self.base_url}: {error.reason}"
            ) from error
        except OSError as error:
            raise ModelUnavailableError(
                f"cannot reach the embedding model server at {self.base_url}: {error}"
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
        for raw_vector in embeddings:
            if not isinstance(raw_vector, list) or not raw_vector:
                raise ModelSchemaError("the embedding model returned an empty vector")
            vector: list[float] = []
            for value in raw_vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ModelSchemaError("an embedding contains a non-numeric value")
                number = float(value)
                if not math.isfinite(number):
                    raise ModelSchemaError("an embedding contains a non-finite value")
                vector.append(number)
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise ModelSchemaError("the embedding vectors have different dimensions")
            vectors.append(vector)
        return vectors

