import json
from datetime import UTC, datetime, timedelta

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.domain.plan import parse_plan, plan_to_dict
from pricor.ports.plan_repository import ColumnFingerprint, SheetFingerprint

from ..domain.golden import golden_plan_dict

T0 = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
FINGERPRINT = SheetFingerprint(
    "Hoja1",
    1,
    (
        ColumnFingerprint(0, "codigo", "code"),
        ColumnFingerprint(1, "descripcion", "text"),
        ColumnFingerprint(2, "precio x caja c/iva", "decimal"),
    ),
)


@pytest.fixture
def database(tmp_path):
    database = SqliteDatabase(tmp_path / "pricor.db")
    yield database
    database.close()


def plan(**changes):
    data = golden_plan_dict()
    data.update(changes)
    return parse_plan(data)


def test_an_unknown_supplier_has_no_plan(database):
    assert database.plans.latest_for("Nadie") is None
    assert database.plans.versions_for("Nadie") == ()


def test_saved_plan_round_trips_with_its_metadata(database):
    original = plan()
    stored = database.plans.save("Ferretería Ejemplo", original, FINGERPRINT, T0)
    loaded = database.plans.latest_for("Ferretería Ejemplo")
    assert loaded == stored
    assert loaded.version == 1
    assert loaded.plan == original
    assert loaded.contract_version == "1"
    assert loaded.engine_version == "0.1.0"
    assert loaded.fingerprint == FINGERPRINT
    assert loaded.created_at == T0
    assert loaded.supplier_name == "Ferretería Ejemplo"


def test_plans_are_stored_as_json_in_the_parse_plan_format(database):
    original = plan()
    database.plans.save("Ferretería Ejemplo", original, FINGERPRINT, T0)
    row = database._connection.execute("select plan_json from plans").fetchone()
    assert parse_plan(json.loads(row[0])) == original
    assert json.loads(row[0]) == plan_to_dict(original)


def test_every_approval_adds_a_version_and_keeps_the_history(database):
    first = plan()
    second = plan(engine_version="0.2.0", confirmed_by_user=["changed"])
    database.plans.save("Ferretería Ejemplo", first, FINGERPRINT, T0)
    database.plans.save("Ferretería Ejemplo", second, FINGERPRINT, T0 + timedelta(days=1))

    latest = database.plans.latest_for("Ferretería Ejemplo")
    versions = database.plans.versions_for("Ferretería Ejemplo")
    assert latest.version == 2
    assert latest.plan == second
    assert [item.version for item in versions] == [1, 2]
    assert versions[0].plan == first  # never overwritten
    assert versions[0].engine_version == "0.1.0"


def test_supplier_identity_ignores_case_spacing_and_nbsp(database):
    database.plans.save("Ferretería  Ejemplo", plan(), FINGERPRINT, T0)
    database.plans.save(" ferretería ejemplo ", plan(), FINGERPRINT, T0)
    assert database.plans.latest_for("FERRETERÍA EJEMPLO").version == 2
    assert database.plans.latest_for("Ferretería Ejemplo").supplier_name == " ferretería ejemplo "
    assert database.plans.latest_for("Otro proveedor") is None


def test_versions_are_counted_per_supplier(database):
    database.plans.save("A", plan(), FINGERPRINT, T0)
    database.plans.save("B", plan(), FINGERPRINT, T0)
    database.plans.save("A", plan(), FINGERPRINT, T0)
    assert database.plans.latest_for("A").version == 2
    assert database.plans.latest_for("B").version == 1


def test_the_fingerprint_is_stored_column_by_column_for_later_comparison(database):
    database.plans.save("A", plan(), FINGERPRINT, T0)
    rows = database._connection.execute(
        "select sheet_name, header_row from plans"
    ).fetchall()
    columns = database._connection.execute(
        "select col_index, header, apparent_type from plan_columns order by col_index"
    ).fetchall()
    assert rows == [("Hoja1", 1)]
    assert columns == [(0, "codigo", "code"), (1, "descripcion", "text"), (2, "precio x caja c/iva", "decimal")]


def test_a_headerless_sheet_fingerprint_round_trips(database):
    headerless = SheetFingerprint("Hoja1", None, (ColumnFingerprint(0, "column_0", "integer"),))
    database.plans.save("A", plan(), headerless, T0)
    assert database.plans.latest_for("A").fingerprint == headerless


def test_plans_survive_reopening_the_file(tmp_path):
    path = tmp_path / "pricor.db"
    first = SqliteDatabase(path)
    first.plans.save("A", plan(), FINGERPRINT, T0)
    first.close()
    second = SqliteDatabase(path)
    assert second.plans.latest_for("A").plan == plan()
    second.close()
