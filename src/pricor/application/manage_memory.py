"""Explicit creation and maintenance of semantic memories."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pricor.ports.embedder import Embedder
from pricor.ports.memory import Memory, MemorySource, MemoryStore
from pricor.ports.model_errors import ModelSchemaError

MAX_MEMORY_TEXT_LENGTH = 1_000


class InvalidMemoryTextError(ValueError):
    """A note is empty after trimming or exceeds the supported size."""


def _validated_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise InvalidMemoryTextError("memory text must not be empty")
    if len(normalized) > MAX_MEMORY_TEXT_LENGTH:
        raise InvalidMemoryTextError(
            f"memory text must be at most {MAX_MEMORY_TEXT_LENGTH:,} characters"
        )
    return normalized


class ManageMemory:
    def __init__(self, store: MemoryStore, embedder: Embedder):
        self._store = store
        self._embedder = embedder

    def create_note(self, text: str, supplier_name: str | None = None) -> Memory:
        return self._create(text, supplier_name, "user_note")

    def create_accepted_suggestion(
        self, text: str, supplier_name: str | None = None
    ) -> Memory:
        return self._create(text, supplier_name, "accepted_suggestion")

    def list(self) -> list[Memory]:
        return self._store.list()

    def edit(self, memory_id: str, text: str) -> Memory:
        normalized = _validated_text(text)
        current = self._store.get(memory_id)
        changed = Memory(
            current.id,
            normalized,
            current.supplier_name,
            current.source,
            current.created_at,
            datetime.now(UTC),
        )
        self._store.update(changed, self._embed_one(normalized))
        return changed

    def delete(self, memory_id: str) -> None:
        self._store.delete(memory_id)

    def relevant(self, query: str, k: int) -> list[Memory]:
        normalized = query.strip()
        if not normalized or k <= 0:
            return []
        return self._store.search(self._embed_one(normalized), k)

    def _create(
        self, text: str, supplier_name: str | None, source: MemorySource
    ) -> Memory:
        normalized = _validated_text(text)
        now = datetime.now(UTC)
        memory = Memory(str(uuid4()), normalized, supplier_name, source, now, now)
        self._store.add(memory, self._embed_one(normalized))
        return memory

    def _embed_one(self, text: str) -> list[float]:
        vectors = self._embedder.embed([text])
        if len(vectors) != 1:
            raise ModelSchemaError("the embedding model did not return one vector")
        return vectors[0]
