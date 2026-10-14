import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.domain.contract import ContractRecord
from pricor.domain.fx import FxSnapshot
from pricor.ports.fx_rates import CachedQuote
from pricor.ports.price_history import ImportedRecord, ImportNotFoundError

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
QUOTED = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path):
    database = SqliteDatabase(tmp_path / "pricor.db")
    yield database
    database.close()


def converted_record():
    return ContractRecord(
        "A1",
        "Antenna",
        Decimal("2.50"),
        "USD",
        unit_cost_net_converted=Decimal("3837.50"),
        fx_rate=Decimal("1535"),
        fx_source="dolarapi:oficial:venta",
        fx_date="2026-10-14",
    )


def test_converted_values_are_stored_next_to_the_original_ones(database):
    plain = ContractRecord("A2", "Plain", Decimal("10.00"), "ARS")
    database.history.record_import(
        "imp-1", "Emilio", T0, [ImportedRecord(1, converted_record()), ImportedRecord(2, plain)]
    )

    loaded = database.history.records_of("imp-1")

    assert [item.record for item in loaded] == [converted_record(), plain]
    assert loaded[0].record.unit_cost_net == Decimal("2.50")  # the original value is untouched
    assert loaded[0].record.currency == "USD"


def test_the_run_snapshot_is_stored_with_the_import_and_round_trips(database):
    snapshot = FxSnapshot(
        Decimal("1535.00"), "oficial", "venta", "dolarapi", QUOTED, "USD", "ARS", stale=True
    )
    database.history.record_import("imp-1", "Emilio", T0, [ImportedRecord(1, converted_record())], fx=snapshot)

    loaded = database.history.fx_of("imp-1")

    assert loaded == snapshot
    assert repr(loaded.rate) == "Decimal('1535.00')"


def test_an_import_without_conversion_has_no_snapshot(database):
    database.history.record_import("imp-1", "A", T0, [])

    assert database.history.fx_of("imp-1") is None


def test_the_snapshot_of_an_unknown_import_is_an_error(database):
    with pytest.raises(ImportNotFoundError):
        database.history.fx_of("missing")


def test_a_failed_import_leaves_no_snapshot_behind(database):
    snapshot = FxSnapshot(Decimal("1"), "manual", "venta", "manual", QUOTED, "USD", "ARS")
    database.history.record_import("imp-1", "A", T0, [], fx=snapshot)

    with pytest.raises(Exception):
        database.history.record_import("imp-1", "A", T0, [], fx=snapshot)

    assert database.history.fx_of("imp-1") == snapshot


def test_money_of_the_snapshot_is_text_never_a_float(tmp_path):
    path = tmp_path / "text.db"
    database = SqliteDatabase(path)
    snapshot = FxSnapshot(Decimal("1535.1"), "oficial", "venta", "dolarapi", QUOTED, "USD", "ARS")
    database.history.record_import("imp-1", "A", T0, [], fx=snapshot)
    database.close()

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("select typeof(rate) from price_import_fx").fetchone() == ("text",)
    finally:
        connection.close()


def test_the_quote_cache_keeps_the_last_quote_per_rate_type(database):
    cache = database.fx_quotes
    first = CachedQuote("oficial", Decimal("1485"), Decimal("1535"), QUOTED)
    newer = CachedQuote("oficial", Decimal("1490.5"), Decimal("1540.25"), datetime(2026, 10, 15, 10, tzinfo=UTC))
    blue = CachedQuote("blue", Decimal("1530"), Decimal("1550"), QUOTED)

    assert cache.last("oficial") is None
    cache.save(first)
    cache.save(blue)
    cache.save(newer)

    assert cache.last("oficial") == newer
    assert cache.last("blue") == blue
    assert cache.last("tarjeta") is None


def test_the_quote_cache_survives_reopening_the_database(tmp_path):
    path = tmp_path / "pricor.db"
    first = SqliteDatabase(path)
    first.fx_quotes.save(CachedQuote("oficial", Decimal("1485"), Decimal("1535"), QUOTED))
    first.close()

    second = SqliteDatabase(path)
    try:
        assert second.fx_quotes.last("oficial").venta == Decimal("1535")
    finally:
        second.close()
