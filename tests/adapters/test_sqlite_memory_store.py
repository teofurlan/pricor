from datetime import UTC, datetime, timedelta

import pytest

from pricor.adapters.sqlite_memory_store import SqliteMemoryStore
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.ports.memory import Memory, MemoryNotFoundError

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def memory(memory_id, text, *, source="user_note", supplier_name=None, updated_at=NOW):
    return Memory(memory_id, text, supplier_name, source, NOW, updated_at)


@pytest.fixture
def database():
    database = SqliteDatabase(":memory:")
    yield database
    database.close()


def test_empty_store_lists_and_searches_nothing(database):
    store = SqliteMemoryStore(database, "bge-m3")

    assert store.list() == []
    assert store.search([1.0, 0.0], 3) == []


def test_add_get_and_list_preserve_the_memory_record(database):
    store = SqliteMemoryStore(database, "bge-m3")
    first = memory("m1", "Remember VAT", supplier_name="Acme")
    second = memory("m2", "Use USD", source="accepted_suggestion")

    store.add(first, [1.0, 0.0])
    store.add(second, [0.0, 1.0])

    assert store.get("m1") == first
    assert store.list() == [second, first]


def test_memory_text_is_stored_as_inert_untrusted_data(database):
    store = SqliteMemoryStore(database, "bge-m3")
    hostile = memory("m1", "'); drop table memories; --")

    store.add(hostile, [1.0])

    assert store.get("m1") == hostile
    store.add(memory("m2", "still available"), [1.0])
    assert len(store.list()) == 2


def test_cosine_search_ranks_descending_and_honors_k(database):
    store = SqliteMemoryStore(database, "bge-m3")
    store.add(memory("same", "same"), [1.0, 0.0])
    store.add(memory("near", "near"), [1.0, 1.0])
    store.add(memory("opposite", "opposite"), [-1.0, 0.0])

    assert [item.id for item in store.search([1.0, 0.0], 2)] == ["same", "near"]


def test_search_only_uses_embeddings_from_the_store_model(database):
    SqliteMemoryStore(database, "old-model").add(memory("old", "old"), [1.0, 0.0])
    current = SqliteMemoryStore(database, "new-model")
    current.add(memory("new", "new"), [1.0, 0.0])

    assert [item.id for item in current.search([1.0, 0.0], 5)] == ["new"]


def test_update_replaces_the_record_and_embedding(database):
    store = SqliteMemoryStore(database, "bge-m3")
    store.add(memory("m1", "old"), [1.0, 0.0])
    changed = memory("m1", "new", updated_at=NOW + timedelta(minutes=1))

    store.update(changed, [0.0, 1.0])

    assert store.get("m1") == changed
    assert store.search([0.0, 1.0], 1) == [changed]


def test_delete_removes_the_memory(database):
    store = SqliteMemoryStore(database, "bge-m3")
    store.add(memory("m1", "delete me"), [1.0])

    store.delete("m1")

    assert store.list() == []
    with pytest.raises(MemoryNotFoundError):
        store.get("m1")


@pytest.mark.parametrize("operation", ["get", "update", "delete"])
def test_unknown_id_raises_a_typed_error(database, operation):
    store = SqliteMemoryStore(database, "bge-m3")

    with pytest.raises(MemoryNotFoundError, match="missing"):
        if operation == "get":
            store.get("missing")
        elif operation == "update":
            store.update(memory("missing", "text"), [1.0])
        else:
            store.delete("missing")
