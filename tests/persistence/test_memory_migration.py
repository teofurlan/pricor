import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from pricor.adapters.sqlite_store import MIGRATIONS, SqliteDatabase

LATEST = MIGRATIONS[-1][0]


@pytest.fixture
def database_path():
    path = Path.cwd() / f".memory-migration-{uuid4().hex}.db"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def memory_columns(path):
    connection = sqlite3.connect(path)
    try:
        return {row[1] for row in connection.execute("pragma table_info(memories)")}
    finally:
        connection.close()


def test_fresh_database_applies_the_memory_migration(database_path):
    path = database_path

    database = SqliteDatabase(path)

    assert database.schema_version() == LATEST
    database.close()
    assert memory_columns(path) == {
        "id",
        "text",
        "supplier_name",
        "source",
        "created_at",
        "updated_at",
        "embedding",
        "embedding_model",
    }


def test_previous_schema_version_upgrades_without_losing_existing_data(database_path):
    path = database_path
    SqliteDatabase(path, migrations=MIGRATIONS[:-1]).close()
    connection = sqlite3.connect(path)
    connection.execute("insert into sessions values ('s1', '{}', '2026-10-18T00:00:00+00:00')")
    connection.commit()
    connection.close()

    database = SqliteDatabase(path)

    assert database.schema_version() == LATEST
    database.close()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("select id from sessions").fetchone() == ("s1",)
    finally:
        connection.close()
    assert "embedding_model" in memory_columns(path)
