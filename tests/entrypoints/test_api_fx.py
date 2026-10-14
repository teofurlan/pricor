from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.domain.fx import FxSnapshot
from pricor.domain.roles import ColumnRole as R
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.ports.fx_rates import FxUnavailableError

from ..application.fakes import FakeClassifier
from .test_api import answer, upload

ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Moneda": (R.CURRENCY, 0.95),
    "Precio": (R.COST_PRICE, 0.9),
}
ROWS = [
    ["Codigo", "Descripcion", "Moneda", "Precio"],
    ["A1", "Antenna", "$", "1846"],
    ["A2", "Mini antenna", "u$s", "2.50"],
]
CONFIRMED_MAP = 'map:{"$":"ARS","u$s":"USD"}'
QUOTED = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


class FakeFx:
    def __init__(self, rate="1535", error=None, stale=False):
        self.rate, self.error, self.stale = rate, error, stale

    def snapshot(self, from_currency, to_currency, rate_type, side):
        if self.error:
            raise self.error
        return FxSnapshot(
            Decimal(self.rate), rate_type, side, "dolarapi", QUOTED, from_currency, to_currency, self.stale
        )


def make_client(fx):
    database = SqliteDatabase(":memory:")
    use_case = ReuseSupplierPlan(
        FileSpreadsheetReader(),
        database.sessions,
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
        plans=database.plans,
        approvals=database,
        fx=fx,
    )
    client = TestClient(create_app(ApiDependencies(use_case)), raise_server_exceptions=False)
    return client, database


@pytest.fixture
def client():
    client, database = make_client(FakeFx())
    yield client
    database.close()


def converted(client, option="oficial:venta"):
    state = upload(client, rows=ROWS, supplier="Emilio").json()
    answer(client, state["id"], "price_includes_vat", "no")
    answer(client, state["id"], "currency", CONFIRMED_MAP)
    return answer(client, state["id"], "fx_conversion", option).json()


def test_a_session_without_conversion_has_no_fx_block():
    client, database = make_client(FakeFx())
    try:
        state = upload(client, rows=ROWS[:1] + [["A1", "Antenna", "$", "1846"]], supplier="X").json()
        answer(client, state["id"], "price_includes_vat", "no")
        answer(client, state["id"], "currency", CONFIRMED_MAP)
        assert client.get(f"/imports/{state['id']}").json()["fx"] is None
    finally:
        database.close()


def test_the_conversion_question_is_part_of_the_questions(client):
    state = upload(client, rows=ROWS, supplier="Emilio").json()
    answer(client, state["id"], "price_includes_vat", "no")
    answer(client, state["id"], "currency", CONFIRMED_MAP)

    state = client.get(f"/imports/{state['id']}").json()

    (question,) = [q for q in state["questions"] if q["id"] == "fx_conversion"]
    tokens = [option["token"] for option in question["options"]]
    assert tokens[0] == "keep" and tokens[-1] == "manual" and "blue:compra" in tokens
    assert question["suggestion"]["option"] == "oficial:venta"
    assert question["suggestion"]["suggested_by"] == "setting"
    assert state["fx"] is None


def test_the_state_reports_the_rate_used(client):
    state = converted(client)

    assert state["status"] == "ready_for_preview"
    assert state["fx"] == {
        "from": "USD",
        "to": "ARS",
        "rate_type": "oficial",
        "side": "venta",
        "error": None,
        "snapshot": {
            "rate": "1535",
            "rate_type": "oficial",
            "side": "venta",
            "source": "dolarapi",
            "quoted_at": "2026-10-14T10:00:00+00:00",
            "date": "2026-10-14",
            "stale": False,
        },
    }


def test_the_preview_carries_original_and_converted_values(client):
    state = converted(client)

    items = client.get(f"/imports/{state['id']}/preview").json()["items"]

    foreign = next(i for i in items if i["record"]["supplier_code"] == "A2")["record"]
    assert foreign["unit_cost_net"] == "2.50" and foreign["currency"] == "USD"
    assert foreign["unit_cost_net_converted"] == "3837.50"
    trace = next(i for i in items if i["record"]["supplier_code"] == "A2")["trace"]
    assert trace[-1] == {"step": "convert_currency", "value": "3837.50"}


def test_an_offline_source_blocks_the_session_until_a_manual_rate_is_entered():
    client, database = make_client(FakeFx(error=FxUnavailableError("cannot reach DolarAPI")))
    try:
        state = converted(client)
        assert state["status"] == "fx_rate_required"
        assert state["fx"]["snapshot"] is None and "cannot reach" in state["fx"]["error"]
        assert client.get(f"/imports/{state['id']}/preview").status_code == 409
        assert client.post(f"/imports/{state['id']}/approve").status_code == 409

        entered = client.put(f"/imports/{state['id']}/fx", json={"rate": "1420,5"})

        assert entered.status_code == 200
        body = entered.json()
        assert body["status"] == "ready_for_preview"
        assert body["fx"]["snapshot"]["source"] == "manual"
        assert body["fx"]["snapshot"]["rate"] == "1420.5"
        assert client.post(f"/imports/{state['id']}/approve").status_code == 200
    finally:
        database.close()


def test_a_bad_manual_rate_is_a_422_and_a_missing_conversion_a_409(client):
    state = converted(client)

    assert client.put(f"/imports/{state['id']}/fx", json={"rate": "abc"}).status_code == 422
    assert client.put(f"/imports/{state['id']}/fx", json={}).status_code == 422
    other = upload(client, rows=ROWS, supplier="Otro").json()
    answer(client, other["id"], "price_includes_vat", "no")
    answer(client, other["id"], "currency", CONFIRMED_MAP)
    answer(client, other["id"], "fx_conversion", "keep")
    assert client.put(f"/imports/{other['id']}/fx", json={"rate": "1500"}).status_code == 409


def test_refresh_asks_the_source_again(client):
    state = converted(client)

    refreshed = client.post(f"/imports/{state['id']}/fx/refresh")

    assert refreshed.status_code == 200
    assert refreshed.json()["fx"]["snapshot"]["rate"] == "1535"


def test_a_stale_rate_is_flagged_in_the_state():
    client, database = make_client(FakeFx(stale=True))
    try:
        assert converted(client)["fx"]["snapshot"]["stale"] is True
    finally:
        database.close()


def test_exports_include_the_converted_columns(client):
    state = converted(client)
    client.post(f"/imports/{state['id']}/approve")

    export = client.get(f"/imports/{state['id']}/export?format=csv").content.decode("utf-8-sig")

    header, first, second = export.splitlines()
    assert "unit_cost_net_converted" in header and "fx_source" in header
    assert "3837.50" in second and "dolarapi:oficial:venta" in second
