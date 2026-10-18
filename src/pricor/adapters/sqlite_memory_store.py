"""SQLite semantic-memory storage with cosine ranking in Python."""

from __future__ import annotations

import json
import math
from contextlib import AbstractContextManager
from datetime import datetime
from sqlite3 import Connection
from typing import Protocol

from pricor.ports.memory import Memory, MemoryNotFoundError


class _Database(Protocol):
    def transaction(self) -> AbstractContextManager[Connection]: ...


def _embedding_json(vector: list[float]) -> str:
    values = [float(value) for value in vector]
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("an embedding must be a non-empty finite vector")
    return json.dumps(values, allow_nan=False, separators=(",", ":"))


def _memory(row) -> Memory:
    return Memory(
        id=row[0],
        text=row[1],
        supplier_name=row[2],
        source=row[3],
        created_at=datetime.fromisoformat(row[4]),
        updated_at=datetime.fromisoformat(row[5]),
    )


class SqliteMemoryStore:
    def __init__(self, database: _Database, embedding_model: str):
        self._db = database
        self._embedding_model = embedding_model

    def add(self, memory: Memory, embedding: list[float]) -> None:
        with self._db.transaction() as connection:
            connection.execute(
                "insert into memories "
                "(id, text, supplier_name, source, created_at, updated_at, embedding, "
                "embedding_model) values (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.id,
                    memory.text,
                    memory.supplier_name,
                    memory.source,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                    _embedding_json(embedding),
                    self._embedding_model,
                ),
            )

    def get(self, memory_id: str) -> Memory:
        with self._db.transaction() as connection:
            row = connection.execute(
                "select id, text, supplier_name, source, created_at, updated_at "
                "from memories where id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError(f"no memory {memory_id!r}")
        return _memory(row)

    def list(self) -> list[Memory]:
        with self._db.transaction() as connection:
            rows = connection.execute(
                "select id, text, supplier_name, source, created_at, updated_at "
                "from memories order by updated_at desc, id desc"
            ).fetchall()
        return [_memory(row) for row in rows]

    def update(self, memory: Memory, embedding: list[float]) -> None:
        with self._db.transaction() as connection:
            result = connection.execute(
                "update memories set text = ?, supplier_name = ?, source = ?, "
                "created_at = ?, updated_at = ?, embedding = ?, embedding_model = ? "
                "where id = ?",
                (
                    memory.text,
                    memory.supplier_name,
                    memory.source,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                    _embedding_json(embedding),
                    self._embedding_model,
                    memory.id,
                ),
            )
        if result.rowcount == 0:
            raise MemoryNotFoundError(f"no memory {memory.id!r}")

    def delete(self, memory_id: str) -> None:
        with self._db.transaction() as connection:
            result = connection.execute("delete from memories where id = ?", (memory_id,))
        if result.rowcount == 0:
            raise MemoryNotFoundError(f"no memory {memory_id!r}")

    def search(self, vector: list[float], k: int) -> list[Memory]:
        if k <= 0:
            return []
        query = [float(value) for value in vector]
        query_norm = math.sqrt(sum(value * value for value in query))
        if not query or not math.isfinite(query_norm):
            raise ValueError("a query embedding must be a non-empty finite vector")
        with self._db.transaction() as connection:
            rows = connection.execute(
                "select id, text, supplier_name, source, created_at, updated_at, embedding "
                "from memories where embedding_model = ? order by updated_at desc, id desc",
                (self._embedding_model,),
            ).fetchall()
        ranked = []
        for row in rows:
            candidate = json.loads(row[6])
            if len(candidate) != len(query):
                continue
            candidate_norm = math.sqrt(sum(value * value for value in candidate))
            similarity = (
                0.0
                if query_norm == 0.0 or candidate_norm == 0.0
                else sum(left * right for left, right in zip(query, candidate, strict=True))
                / (query_norm * candidate_norm)
            )
            ranked.append((similarity, _memory(row)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [memory for _, memory in ranked[:k]]
