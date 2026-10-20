import sqlite3

import pytest

from pricor.adapters.sqlite_store import MIGRATIONS, SqliteDatabase


@pytest.mark.parametrize("previous", [False, True])
def test_output_format_migration_on_fresh_and_previous_database(tmp_path, previous):
    path = tmp_path / "output.db"
    if previous:
        db = SqliteDatabase(path, migrations=MIGRATIONS[:3])
        with db.transaction() as connection:
            connection.execute("insert into sessions values ('old', '{}', '2026-10-19')")
            connection.execute("insert into memories values ('m', 'note', null, 'user_note', 'date', 'date', '[1]', 'bge-m3')")
        db.close()
    db = SqliteDatabase(path)
    assert MIGRATIONS[-1][0] == db.schema_version() == 4
    assert db.output_format.get() is None
    db.close()
    db = SqliteDatabase(path)
    assert db.schema_version() == 4
    db.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("select version from schema_version order by version").fetchall() == [(1,), (2,), (3,), (4,)]
        if previous:
            assert connection.execute("select id from sessions").fetchall() == [("old",)]
            assert connection.execute("select text from memories").fetchall() == [("note",)]
