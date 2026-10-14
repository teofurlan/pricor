import sqlite3

import pytest

from pricor.adapters.sqlite_store import SchemaVersionError, SqliteDatabase


def tables(path):
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
    finally:
        connection.close()


def test_creates_the_schema_and_records_its_version(tmp_path):
    path = tmp_path / "pricor.db"
    database = SqliteDatabase(path)
    assert database.schema_version() == 1
    database.close()
    assert {"schema_version", "plans", "plan_columns", "price_imports", "price_records", "sessions"} <= tables(path)


def test_opening_twice_is_idempotent_and_keeps_data(tmp_path):
    path = tmp_path / "pricor.db"
    SqliteDatabase(path).close()
    database = SqliteDatabase(path)
    assert database.schema_version() == 1
    database.close()
    connection = sqlite3.connect(path)
    assert [row[0] for row in connection.execute("select version from schema_version")] == [1]
    connection.close()


def test_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "pricor.db"
    SqliteDatabase(path).close()
    assert path.exists()


def test_later_migrations_apply_on_top_of_earlier_ones(tmp_path):
    from pricor.adapters.sqlite_store import MIGRATIONS

    path = tmp_path / "pricor.db"
    SqliteDatabase(path).close()
    extra = (*MIGRATIONS, (2, ["create table extra (id integer primary key)"]))
    database = SqliteDatabase(path, migrations=extra)
    assert database.schema_version() == 2
    database.close()
    assert "extra" in tables(path)


def test_a_failing_migration_rolls_back_completely(tmp_path):
    from pricor.adapters.sqlite_store import MIGRATIONS

    path = tmp_path / "pricor.db"
    SqliteDatabase(path).close()
    broken = (
        *MIGRATIONS,
        (2, ["create table half_done (id integer)", "this is not sql"]),
    )
    with pytest.raises(sqlite3.Error):
        SqliteDatabase(path, migrations=broken)
    assert "half_done" not in tables(path)
    assert SqliteDatabase(path).schema_version() == 1


def test_a_database_from_a_newer_version_is_refused(tmp_path):
    from pricor.adapters.sqlite_store import MIGRATIONS

    path = tmp_path / "pricor.db"
    SqliteDatabase(path, migrations=(*MIGRATIONS, (2, ["create table extra (id integer)"]))).close()
    with pytest.raises(SchemaVersionError):
        SqliteDatabase(path)
