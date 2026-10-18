"""Port and records for explicit semantic memories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

MemorySource = Literal["user_note", "accepted_suggestion"]


class MemoryNotFoundError(LookupError):
    """The requested memory id does not exist."""


@dataclass(frozen=True)
class Memory:
    id: str
    text: str
    supplier_name: str | None
    source: MemorySource
    created_at: datetime
    updated_at: datetime


class MemoryStore(Protocol):
    def add(self, memory: Memory, embedding: list[float]) -> None: ...

    def get(self, memory_id: str) -> Memory: ...

    def list(self) -> list[Memory]: ...

    def update(self, memory: Memory, embedding: list[float]) -> None: ...

    def delete(self, memory_id: str) -> None: ...

    def search(self, vector: list[float], k: int) -> list[Memory]: ...
