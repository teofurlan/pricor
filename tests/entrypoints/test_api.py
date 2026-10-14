import csv
import io

import pytest
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.domain.roles import ColumnRole as R
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.entrypoints.wiring import dependencies_from_env, ollama_client_from_env
from pricor.ports.model_errors import ModelUnavailableError
from pricor.ports.plan_advisor import (
    Evidence,
    ParameterHypothesis,
    ParameterId,
    PlanProposal,
)

from ..application.fakes import FakeAdvisor, FakeClassifier

ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Precio lista": (R.COST_PRICE, 0.9),
    "IVA": (R.VAT_RATE, 0.9),
}
ROWS = [
    ["LISTA OCTUBRE", "", "", ""],
    ["Codigo", "Descripcion", "Precio lista", "IVA"],
    ["A1", "Tornillo", "1.210,00", "21%"],
    ["A2", "Tuerca", "968,00", "21%"],
    ["A3", "Arandela", "121,00", "21%"],
    ["A4", "Clavo", "60,50", "21%"],
    ["A5", "Taco", "1.815,00", "21%"],
    ["A6", "Brida", "abc", "21%"],
    ["", "", "", ""],
    ["TOTAL", "", "4.174,50", ""],
]


def csv_bytes(rows):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode("utf-8")


def make_client(advisor=None, table=ROLES, max_upload_bytes=1024 * 1024, stages=None):
    stages = stages or [ClassifierStage("heuristics", FakeClassifier(table))]
    use_case = ImportFirstTime(
        FileSpreadsheetReader(), InMemoryImportSessionRepository(), stages, advisor
    )
    app = create_app(ApiDependencies(use_case, max_upload_bytes=max_upload_bytes))
    return TestClient(app, raise_server_exceptions=False)


def upload(client, rows=ROWS, filename="lista.csv", supplier="Ferreteria Ejemplo", **form):
    return client.post(
        "/imports",
        files={"file": (filename, csv_bytes(rows), "text/csv")},
        data={"supplier_name": supplier, **form},
    )


def answer(client, session_id, question_id, option):
    return client.post(
        f"/imports/{session_id}/answers", json={"question_id": question_id, "option": option}
    )


def test_full_flow_over_http():
    client = make_client()
    created = upload(client, language="es")
    assert created.status_code == 201
    state = created.json()
    assert state["status"] == "questions_pending"
    assert state["file_name"] == "lista.csv"
    assert sorted(q["id"] for q in state["questions"]) == ["currency", "price_includes_vat"]
    question = state["questions"][0]
    assert question["text"]["en"] and question["text"]["es"]
    assert {"token", "label"} <= set(question["options"][0])
    assert [c["decided_by"] for c in state["columns"]] == ["heuristics"] * 4

    session_id = state["id"]
    assert answer(client, session_id, "price_includes_vat", "yes").status_code == 200
    final = answer(client, session_id, "currency", "ARS").json()
    assert final["status"] == "ready_for_preview"
    assert final["answers"] == {"price_includes_vat": "yes", "currency": "ARS"}

    preview = client.get(f"/imports/{session_id}/preview", params={"limit": 2}).json()
    assert preview["totals"]["accepted"] == 5
    assert preview["totals"]["rejected"] == 1
    assert preview["totals"]["rejected_rows"][0]["row_number"] == 8
    assert [i["row_number"] for i in preview["items"]] == [3, 4]
    assert preview["items"][0]["record"]["unit_cost_net"] == "1000.00"
    assert preview["items"][0]["trace"][0]["step"] == "original"
    assert preview["total_items"] == 6

    approved = client.post(f"/imports/{session_id}/approve").json()
    assert approved["status"] == "approved"
    assert client.get(f"/imports/{session_id}").json()["approved"] is True
    frozen = answer(client, session_id, "currency", "USD")
    assert frozen.status_code == 409


def test_headerless_file_needs_a_header_choice():
    client = make_client(table={})
    rows = [["A1", "Tornillo", "10,50"], ["A2", "Tuerca", "11,50"]]
    state = upload(client, rows).json()
    assert state["status"] == "header_choice_required"
    assert [c["row_index"] for c in state["header"]["candidates"]] == [0, 1]

    chosen = client.put(f"/imports/{state['id']}/header", json={"row_index": None}).json()
    assert [c["header"] for c in chosen["columns"]] == ["column_0", "column_1", "column_2"]
    assert chosen["status"] == "role_confirmation_required"


def test_roles_can_be_set_by_the_user():
    client = make_client(table={"Codigo": (R.CODE, 0.95)})
    state = upload(client).json()
    assert state["status"] == "role_confirmation_required"
    updated = client.put(
        f"/imports/{state['id']}/roles",
        json={"roles": {"1": "description", "2": "cost_price", "3": "vat_rate"}},
    ).json()
    assert updated["status"] == "questions_pending"
    assert updated["columns"][2]["decided_by"] == "user"
    assert updated["columns"][2]["role"] == "cost_price"


def test_model_hypothesis_is_exposed_only_as_a_suggestion():
    hypothesis = ParameterHypothesis(ParameterId.PRICE_INCLUDES_VAT, True, 0.7, (Evidence(3, "21%"),))
    advisor = FakeAdvisor(PlanProposal((hypothesis,), ()))
    state = upload(make_client(advisor)).json()
    vat = next(q for q in state["questions"] if q["id"] == "price_includes_vat")
    assert vat["suggestion"]["suggested_by"] == "model"
    assert vat["suggestion"]["option"] == "yes"
    assert vat["suggestion"]["calibrated"] is False
    assert state["answers"] == {}
    assert state["status"] == "questions_pending"


def test_model_failure_is_a_visible_notice_and_the_flow_continues():
    advisor = FakeAdvisor(error=ModelUnavailableError("ollama is down"))
    state = upload(make_client(advisor)).json()
    assert [n["code"] for n in state["notices"]] == ["model_unavailable"]
    assert len(state["questions"]) == 2


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "status", "code"),
    [
        ("get", "/imports/nope", {}, 404, "session_not_found"),
        ("get", "/imports/nope/preview", {}, 404, "session_not_found"),
        ("post", "/imports/nope/approve", {}, 404, "session_not_found"),
        ("put", "/imports/nope/header", {"json": {"row_index": 1}}, 404, "session_not_found"),
        ("post", "/imports", {"data": {"supplier_name": "X"}}, 422, "invalid_request"),
    ],
)
def test_errors_use_one_json_envelope(method, path, kwargs, status, code):
    response = getattr(make_client(), method)(path, **kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert set(response.json()) == {"error"}


def test_state_conflicts_and_invalid_input_map_to_409_and_422():
    client = make_client()
    session_id = upload(client).json()["id"]
    assert client.get(f"/imports/{session_id}/preview").status_code == 409
    assert client.post(f"/imports/{session_id}/approve").status_code == 409
    assert answer(client, session_id, "price_includes_vat", "maybe").status_code == 422
    assert answer(client, session_id, "units_per_pack", "constant:3").status_code == 422
    assert client.put(f"/imports/{session_id}/header", json={"row_index": 999}).status_code == 422
    assert (
        client.put(f"/imports/{session_id}/roles", json={"roles": {"0": "bogus"}}).status_code
        == 422
    )
    assert (
        client.put(f"/imports/{session_id}/roles", json={"roles": {"99": "code"}}).status_code
        == 422
    )
    assert client.get(f"/imports/{session_id}/preview", params={"limit": 0}).status_code == 422
    assert upload(client, language="fr").status_code == 422
    assert upload(client, supplier="  ").status_code == 422


def test_upload_rejects_unsupported_extensions_without_a_stack_trace():
    response = upload(make_client(), filename="lista.exe")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_format"
    assert "Traceback" not in response.text


def test_upload_enforces_the_size_limit():
    response = upload(make_client(max_upload_bytes=50))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_unreadable_file_is_a_422_not_a_crash():
    client = make_client()
    response = client.post(
        "/imports",
        files={"file": ("broken.xlsx", b"this is not a workbook", "application/octet-stream")},
        data={"supplier_name": "X"},
    )
    assert response.status_code == 422
    assert "Traceback" not in response.text


def test_uploaded_file_names_cannot_escape_the_upload_directory(tmp_path):
    use_case = ImportFirstTime(
        FileSpreadsheetReader(),
        InMemoryImportSessionRepository(),
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
    )
    client = TestClient(
        create_app(ApiDependencies(use_case, upload_dir=tmp_path)), raise_server_exceptions=False
    )
    response = upload(client, filename="../../evil.csv")
    assert response.status_code == 201
    assert response.json()["file_name"] == "evil.csv"
    assert list(tmp_path.iterdir()) == []  # temporary uploads are removed after reading


def test_unexpected_errors_are_hidden_behind_a_generic_500():
    class Boom:
        def classify_sheet(self, sheet):
            raise RuntimeError("secret internals")

    client = make_client(stages=[ClassifierStage("heuristics", Boom())])
    response = upload(client)
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "unexpected server error"}
    }


def test_wiring_reads_ollama_settings_from_the_environment():
    client = ollama_client_from_env(
        {
            "PRICOR_OLLAMA_URL": "http://example:1234/",
            "PRICOR_OLLAMA_MODEL": "other:model",
            "PRICOR_OLLAMA_TIMEOUT": "12.5",
        }
    )
    assert (client.base_url, client.model, client.timeout) == (
        "http://example:1234",
        "other:model",
        12.5,
    )
    defaults = ollama_client_from_env({})
    assert (defaults.base_url, defaults.model) == ("http://localhost:11434", "gemma4:e4b")
    with pytest.raises(ValueError, match="PRICOR_OLLAMA_TIMEOUT"):
        ollama_client_from_env({"PRICOR_OLLAMA_TIMEOUT": "soon"})
    assert dependencies_from_env({}).max_upload_bytes == 20 * 1024 * 1024


def test_approving_with_no_accepted_rows_is_a_409():
    rows = [
        ["Codigo", "Descripcion", "Precio lista", "IVA"],
        ["", "Tornillo", "1.210,00", "21%"],
        ["", "Tuerca", "968,00", "21%"],
    ]
    client = make_client()
    session_id = upload(client, rows=rows).json()["id"]
    answer(client, session_id, "price_includes_vat", "yes")
    answer(client, session_id, "currency", "ARS")

    response = client.post(f"/imports/{session_id}/approve")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_accepted_rows"
    assert client.get(f"/imports/{session_id}").json()["approved"] is False
