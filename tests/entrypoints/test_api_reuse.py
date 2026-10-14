import pytest
from fastapi.testclient import TestClient

from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.entrypoints.api import ApiDependencies, create_app

from ..application.fakes import FakeClassifier
from .test_api import ROLES, ROWS, answer, upload

CLEAN = [row for row in ROWS if row[0] not in ("LISTA OCTUBRE", "TOTAL", "", "A6")]


@pytest.fixture
def client():
    database = SqliteDatabase(":memory:")
    use_case = ReuseSupplierPlan(
        FileSpreadsheetReader(),
        database.sessions,
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
        plans=database.plans,
        approvals=database,
    )
    yield TestClient(create_app(ApiDependencies(use_case)), raise_server_exceptions=False)
    database.close()


def approved_first_import(client, rows=CLEAN):
    state = upload(client, rows=rows).json()
    assert state["mode"] == "first_import"
    for question in state["questions"]:
        option = {"price_includes_vat": "yes", "currency": "ARS"}[question["id"]]
        assert answer(client, state["id"], question["id"], option).status_code == 200
    assert client.post(f"/imports/{state['id']}/approve").status_code == 200
    return state["id"]


def test_a_first_import_reports_no_reuse(client):
    state = upload(client, rows=CLEAN).json()

    assert state["mode"] == "first_import"
    assert state["based_on_plan_version"] is None
    assert state["changes"] == []


def test_a_known_supplier_reuses_its_plan_and_goes_straight_to_ready(client):
    approved_first_import(client)

    state = upload(client, rows=CLEAN).json()

    assert state["mode"] == "reuse"
    assert state["based_on_plan_version"] == 1
    assert state["changes"] == []
    assert state["status"] == "ready_for_preview"
    assert state["questions"] == []
    assert {column["decided_by"] for column in state["columns"]} == {"saved_plan"}
    assert state["answers"] == {"price_includes_vat": "yes", "currency": "ARS"}


def test_a_moved_column_appears_in_the_structured_change_list(client):
    approved_first_import(client)
    swapped = [[row[1], row[0], row[2], row[3]] for row in CLEAN]

    state = upload(client, rows=swapped).json()

    assert state["status"] == "ready_for_preview"
    assert state["changes"] == [
        {
            "kind": "moved",
            "header": "codigo",
            "old_index": 0,
            "new_index": 1,
            "old_type": "code",
            "new_type": "code",
            "used_by_plan": False,
            "role": "code",
            "old_value": None,
            "new_value": None,
        },
        {
            "kind": "moved",
            "header": "descripcion",
            "old_index": 1,
            "new_index": 0,
            "old_type": "text",
            "new_type": "text",
            "used_by_plan": False,
            "role": "description",
            "old_value": None,
            "new_value": None,
        },
    ]
    preview = client.get(f"/imports/{state['id']}/preview").json()
    assert preview["items"][0]["record"]["supplier_code"] == "A1"


def test_a_new_column_needs_the_user_before_the_preview(client):
    approved_first_import(client)
    wider = [[*row, "Stock" if n == 0 else "5"] for n, row in enumerate(CLEAN)]

    state = upload(client, rows=wider).json()

    assert state["status"] == "role_confirmation_required"
    assert [(c["kind"], c["header"]) for c in state["changes"]] == [("new", "stock")]
    stock = state["columns"][4]
    assert (stock["role"], stock["decided_by"]) == (None, None)


def test_a_fresh_import_can_be_forced(client):
    approved_first_import(client)

    state = upload(client, rows=CLEAN, force_first_import="true").json()

    assert state["mode"] == "first_import"
    assert state["based_on_plan_version"] is None
    assert state["status"] == "questions_pending"


def test_approving_a_reused_import_adds_a_plan_version(client):
    approved_first_import(client)
    state = upload(client, rows=CLEAN).json()

    approved = client.post(f"/imports/{state['id']}/approve").json()
    again = upload(client, rows=CLEAN).json()

    assert approved["approved"] is True
    assert again["based_on_plan_version"] == 2


def test_the_wired_app_reuses_plans(tmp_path):
    from pricor.entrypoints.wiring import dependencies_from_env

    dependencies = dependencies_from_env({"PRICOR_DB": str(tmp_path / "pricor.db")})

    assert isinstance(dependencies.use_case, ReuseSupplierPlan)
