"""SQLite persistence: sessions, supplier plans and price history in one file.

Standard library `sqlite3` only. One `SqliteDatabase` owns the connection and
hands out the three repositories; `approval()` opens a single transaction that
all of them join, so an approval is all-or-nothing. Money is stored as TEXT
decimals (`str(Decimal)`), never REAL.

Schema changes are numbered migrations applied at startup inside one
transaction; opening a database that is already current does nothing, and a
database written by a newer Pricor is refused instead of guessed at.

The connection is shared by FastAPI worker threads, so every operation holds
one re-entrant lock.
"""

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pricor.adapters.session_codec import decode, encode
from pricor.domain.contract import ContractRecord
from pricor.domain.parsing import lookup_key
from pricor.domain.plan import ImportPlan, parse_plan, plan_to_dict
from pricor.ports.import_session import ImportSession
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.plan_repository import ColumnFingerprint, SheetFingerprint, StoredPlan
from pricor.ports.price_history import (
    DuplicateImportError,
    ImportedRecord,
    ImportNotFoundError,
    ImportSummary,
)

Migration = tuple[int, Sequence[str]]

MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        [
            """create table plans (
                id integer primary key autoincrement,
                supplier_key text not null,
                supplier_name text not null,
                version integer not null,
                contract_version text not null,
                engine_version text not null,
                plan_json text not null,
                sheet_name text not null,
                header_row integer,
                created_at text not null,
                unique (supplier_key, version)
            )""",
            """create table plan_columns (
                plan_id integer not null references plans(id),
                col_index integer not null,
                header text not null,
                apparent_type text not null,
                primary key (plan_id, col_index)
            )""",
            """create table price_imports (
                import_id text primary key,
                supplier_key text not null,
                supplier_name text not null,
                imported_at text not null
            )""",
            "create index price_imports_supplier on price_imports (supplier_key, imported_at)",
            """create table price_records (
                import_id text not null references price_imports(import_id),
                row_number integer not null,
                supplier_code text not null,
                description text not null,
                unit_cost_net text not null,
                currency text not null,
                vat_rate text,
                units_per_pack text,
                barcode text,
                suggested_retail_price text,
                primary key (import_id, row_number)
            )""",
            "create index price_records_code on price_records (import_id, supplier_code)",
            """create table sessions (
                id text primary key,
                data text not null,
                updated_at text not null
            )""",
        ],
    ),
)


class SchemaVersionError(Exception):
    """The database was written by a newer Pricor than this one."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteDatabase:
    def __init__(self, path: str | Path, migrations: Sequence[Migration] = MIGRATIONS):
        self._lock = threading.RLock()
        self._depth = 0
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode: transactions are explicit (`transaction()`).
        self._connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        try:
            self._connection.execute("pragma foreign_keys = on")
            self._migrate(migrations)
        except BaseException:
            self._connection.close()
            raise
        self.sessions = SqliteImportSessionRepository(self)
        self.plans = SqlitePlanRepository(self)
        self.history = SqlitePriceHistory(self)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One transaction; a nested call joins the outer one."""
        with self._lock:
            if self._depth:
                yield self._connection
                return
            self._connection.execute("begin immediate")
            self._depth = 1
            try:
                yield self._connection
                self._connection.execute("commit")
            except BaseException:
                self._connection.execute("rollback")
                raise
            finally:
                self._depth = 0

    @contextmanager
    def approval(self) -> Iterator["SqliteDatabase"]:
        """Plans, history and sessions written inside this block commit together."""
        with self.transaction():
            yield self

    def schema_version(self) -> int:
        with self.transaction() as connection:
            return self._current_version(connection)

    @staticmethod
    def _current_version(connection: sqlite3.Connection) -> int:
        row = connection.execute("select max(version) from schema_version").fetchone()
        return row[0] or 0

    def _migrate(self, migrations: Sequence[Migration]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "create table if not exists schema_version "
                "(version integer primary key, applied_at text not null)"
            )
            current = self._current_version(connection)
            latest = max((version for version, _ in migrations), default=0)
            if current > latest:
                raise SchemaVersionError(
                    f"the database is at schema version {current}, "
                    f"but this Pricor only knows up to {latest}"
                )
            for version, statements in sorted(migrations, key=lambda item: item[0]):
                if version <= current:
                    continue
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "insert into schema_version (version, applied_at) values (?, ?)",
                    (version, _now()),
                )


# -- sessions -----------------------------------------------------------------------


class SqliteImportSessionRepository:
    def __init__(self, database: SqliteDatabase):
        self._db = database

    def add(self, session: ImportSession) -> None:
        with self._db.transaction() as connection:
            connection.execute(
                "insert or replace into sessions (id, data, updated_at) values (?, ?, ?)",
                (session.id, encode(session), _now()),
            )

    def get(self, session_id: str) -> ImportSession:
        with self._db.transaction() as connection:
            row = connection.execute(
                "select data from sessions where id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise SessionNotFoundError(f"no import session {session_id!r}")
        return decode(row[0])

    def save(self, session: ImportSession) -> None:
        with self._db.transaction() as connection:
            updated = connection.execute(
                "update sessions set data = ?, updated_at = ? where id = ?",
                (encode(session), _now(), session.id),
            )
            if updated.rowcount == 0:
                raise SessionNotFoundError(f"no import session {session.id!r}")


# -- plans --------------------------------------------------------------------------

_PLAN_COLUMNS = (
    "id, supplier_key, supplier_name, version, plan_json, sheet_name, header_row, created_at"
)


class SqlitePlanRepository:
    def __init__(self, database: SqliteDatabase):
        self._db = database

    def save(
        self, supplier: str, plan: ImportPlan, fingerprint: SheetFingerprint, created_at: datetime
    ) -> StoredPlan:
        key = lookup_key(supplier)
        with self._db.transaction() as connection:
            version = connection.execute(
                "select coalesce(max(version), 0) + 1 from plans where supplier_key = ?", (key,)
            ).fetchone()[0]
            plan_id = connection.execute(
                "insert into plans (supplier_key, supplier_name, version, contract_version, "
                "engine_version, plan_json, sheet_name, header_row, created_at) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    supplier,
                    version,
                    plan.contract_version,
                    plan.engine_version,
                    json.dumps(plan_to_dict(plan), ensure_ascii=False),
                    fingerprint.sheet_name,
                    fingerprint.header_row,
                    created_at.isoformat(),
                ),
            ).lastrowid
            connection.executemany(
                "insert into plan_columns (plan_id, col_index, header, apparent_type) "
                "values (?, ?, ?, ?)",
                [
                    (plan_id, column.index, column.header, column.apparent_type)
                    for column in fingerprint.columns
                ],
            )
        return StoredPlan(key, supplier, version, plan, fingerprint, created_at)

    def latest_for(self, supplier: str) -> StoredPlan | None:
        versions = self._load(supplier, newest_only=True)
        return versions[0] if versions else None

    def versions_for(self, supplier: str) -> tuple[StoredPlan, ...]:
        return tuple(self._load(supplier, newest_only=False))

    def _load(self, supplier: str, *, newest_only: bool) -> list[StoredPlan]:
        order = "desc limit 1" if newest_only else "asc"
        with self._db.transaction() as connection:
            rows = connection.execute(
                f"select {_PLAN_COLUMNS} from plans where supplier_key = ? "
                f"order by version {order}",
                (lookup_key(supplier),),
            ).fetchall()
            stored = []
            for plan_id, key, name, version, plan_json, sheet, header_row, created in rows:
                columns = connection.execute(
                    "select col_index, header, apparent_type from plan_columns "
                    "where plan_id = ? order by col_index",
                    (plan_id,),
                ).fetchall()
                stored.append(
                    StoredPlan(
                        key,
                        name,
                        version,
                        parse_plan(json.loads(plan_json)),
                        SheetFingerprint(
                            sheet, header_row, tuple(ColumnFingerprint(*item) for item in columns)
                        ),
                        datetime.fromisoformat(created),
                    )
                )
        return stored


# -- price history ------------------------------------------------------------------


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


class SqlitePriceHistory:
    def __init__(self, database: SqliteDatabase):
        self._db = database

    def record_import(
        self,
        import_id: str,
        supplier: str,
        imported_at: datetime,
        records: Sequence[ImportedRecord],
    ) -> None:
        with self._db.transaction() as connection:
            try:
                connection.execute(
                    "insert into price_imports (import_id, supplier_key, supplier_name, imported_at) "
                    "values (?, ?, ?, ?)",
                    (import_id, lookup_key(supplier), supplier, imported_at.isoformat()),
                )
            except sqlite3.IntegrityError as error:
                raise DuplicateImportError(f"import {import_id!r} is already stored") from error
            connection.executemany(
                "insert into price_records (import_id, row_number, supplier_code, description, "
                "unit_cost_net, currency, vat_rate, units_per_pack, barcode, "
                "suggested_retail_price) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        import_id,
                        item.row_number,
                        item.record.supplier_code,
                        item.record.description,
                        str(item.record.unit_cost_net),
                        item.record.currency,
                        _text(item.record.vat_rate),
                        _text(item.record.units_per_pack),
                        item.record.barcode,
                        _text(item.record.suggested_retail_price),
                    )
                    for item in records
                ],
            )

    def imports_for(self, supplier: str) -> tuple[ImportSummary, ...]:
        with self._db.transaction() as connection:
            rows = connection.execute(
                "select i.import_id, i.supplier_key, i.supplier_name, i.imported_at, "
                "(select count(*) from price_records r where r.import_id = i.import_id) "
                "from price_imports i where i.supplier_key = ? "
                "order by i.imported_at, i.rowid",
                (lookup_key(supplier),),
            ).fetchall()
        return tuple(
            ImportSummary(import_id, key, name, datetime.fromisoformat(at), count)
            for import_id, key, name, at, count in rows
        )

    def records_of(self, import_id: str) -> tuple[ImportedRecord, ...]:
        with self._db.transaction() as connection:
            if connection.execute(
                "select 1 from price_imports where import_id = ?", (import_id,)
            ).fetchone() is None:
                raise ImportNotFoundError(f"no stored import {import_id!r}")
            rows = connection.execute(
                "select row_number, supplier_code, description, unit_cost_net, currency, "
                "vat_rate, units_per_pack, barcode, suggested_retail_price "
                "from price_records where import_id = ? order by row_number",
                (import_id,),
            ).fetchall()
        return tuple(
            ImportedRecord(
                number,
                ContractRecord(
                    code,
                    description,
                    Decimal(cost),
                    currency,
                    _decimal(vat),
                    _decimal(units),
                    barcode,
                    _decimal(retail),
                ),
            )
            for number, code, description, cost, currency, vat, units, barcode, retail in rows
        )
