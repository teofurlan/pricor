from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.domain.contract import ContractRecord
from pricor.ports.price_history import DuplicateImportError, ImportedRecord, ImportNotFoundError

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path):
    database = SqliteDatabase(tmp_path / "pricor.db")
    yield database
    database.close()


def record(code="A1", cost="855.00", **fields):
    return ContractRecord(code, f"Item {code}", Decimal(cost), "ARS", **fields)


def test_records_round_trip_with_exact_decimals_and_every_optional_field(database):
    full = ImportedRecord(
        3,
        ContractRecord(
            "00123",
            "Tornillo 1/4",
            Decimal("855.00"),
            "ARS",
            vat_rate=Decimal("10.5"),
            units_per_pack=Decimal("12"),
            barcode="0779123456789",
            suggested_retail_price=Decimal("1234.50"),
        ),
    )
    bare = ImportedRecord(4, record("A2", "0.1"))
    database.history.record_import("imp-1", "Ferretería", T0, [full, bare])

    loaded = database.history.records_of("imp-1")
    assert loaded == (full, bare)
    assert repr(loaded) == repr((full, bare))  # Decimal('855.00') keeps its exponent
    assert loaded[0].record.supplier_code == "00123"  # leading zeros survive
    assert loaded[0].record.barcode == "0779123456789"
    assert loaded[1].record.vat_rate is None


def test_money_is_stored_as_text_never_as_a_float(database):
    database.history.record_import("imp-1", "A", T0, [ImportedRecord(1, record(cost="0.1", vat_rate=Decimal("21")))])
    row = database._connection.execute(
        "select typeof(unit_cost_net), unit_cost_net, typeof(vat_rate), typeof(units_per_pack) "
        "from price_records"
    ).fetchone()
    assert row == ("text", "0.1", "text", "null")
    declared = database._connection.execute("pragma table_info(price_records)").fetchall()
    assert not [column for column in declared if column[2].lower() in ("real", "float", "double", "numeric")]


def test_records_come_back_in_file_order(database):
    rows = [ImportedRecord(n, record(f"C{n}")) for n in (9, 3, 7)]
    database.history.record_import("imp-1", "A", T0, rows)
    assert [item.row_number for item in database.history.records_of("imp-1")] == [3, 7, 9]


def test_imports_are_listed_per_supplier_oldest_first(database):
    database.history.record_import("late", "Ferretería", T0 + timedelta(days=2), [ImportedRecord(1, record())])
    database.history.record_import("early", "ferretería ", T0, [ImportedRecord(1, record()), ImportedRecord(2, record("A2"))])
    database.history.record_import("other", "Otra", T0, [ImportedRecord(1, record())])

    summaries = database.history.imports_for("FERRETERÍA")
    assert [(item.import_id, item.record_count) for item in summaries] == [("early", 2), ("late", 1)]
    assert summaries[0].imported_at == T0
    assert summaries[0].supplier_name == "ferretería "
    assert [item.import_id for item in database.history.imports_for("Otra")] == ["other"]
    assert database.history.imports_for("Nadie") == ()


def test_unknown_import_is_reported(database):
    with pytest.raises(ImportNotFoundError):
        database.history.records_of("missing")


def test_an_import_id_is_stored_only_once(database):
    database.history.record_import("imp-1", "A", T0, [ImportedRecord(1, record())])
    with pytest.raises(DuplicateImportError):
        database.history.record_import("imp-1", "A", T0, [ImportedRecord(1, record("B"))])
    assert [item.record.supplier_code for item in database.history.records_of("imp-1")] == ["A1"]


def test_an_import_with_no_records_is_still_listed(database):
    database.history.record_import("empty", "A", T0, [])
    assert database.history.imports_for("A")[0].record_count == 0
    assert database.history.records_of("empty") == ()


def test_history_survives_reopening_the_file(tmp_path):
    path = tmp_path / "pricor.db"
    first = SqliteDatabase(path)
    first.history.record_import("imp-1", "A", T0, [ImportedRecord(1, record())])
    first.close()
    second = SqliteDatabase(path)
    assert second.history.records_of("imp-1")[0].record.unit_cost_net == Decimal("855.00")
    second.close()
