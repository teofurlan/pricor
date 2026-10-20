import pytest
from fastapi.testclient import TestClient

from pricor.adapters.gemma_question_helper import GemmaQuestionHelper
from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.ports.model_errors import ModelInvalidJsonError, ModelTimeoutError, ModelUnavailableError

from ..adapters.gemma_fakes import FakeClient
from ..application.fakes import FakeClassifier
from .test_api import ROLES, answer, upload


@pytest.fixture
def api():
    chat = FakeClient({"reply": "Check whether your supplier includes VAT.", "suggested_option": "no"})
    imports = ImportFirstTime(FileSpreadsheetReader(), InMemoryImportSessionRepository(), [ClassifierStage("fake", FakeClassifier(ROLES))])
    client = TestClient(create_app(ApiDependencies(imports, question_helper=GemmaQuestionHelper(chat))), raise_server_exceptions=False)
    created = upload(client, language="es")
    assert created.status_code == 201
    return client, created.json(), chat


def path(session_id, question="price_includes_vat"):
    return f"/imports/{session_id}/questions/{question}/ask"


def test_200_reply_trimmed_message_bounded_history_and_no_implicit_answer(api):
    client, state, chat = api
    history = [{"role": role, "text": "x" * 1200} for role in ["user", "model"] * 3]
    response = client.post(path(state["id"]), json={"message": "  Explain VAT  ", "history": history})
    assert response.status_code == 200
    assert response.json() == {"reply": "Check whether your supplier includes VAT.", "suggested_option": "no"}
    assert '"message": "Explain VAT"' in chat.calls[0]["user"]
    assert client.get(f"/imports/{state['id']}").json() == state
    # Ask is advisory; only the existing answer endpoint changes the plan.
    updated = answer(client, state["id"], "price_includes_vat", "yes")
    assert updated.status_code == 200
    assert updated.json()["answers"] == {"price_includes_vat": "yes"}


@pytest.mark.parametrize("message", ["x", "x" * 500, "  " + "x" * 500 + "  "])
def test_message_boundaries_and_optional_history(api, message):
    client, state, _ = api
    assert client.post(path(state["id"]), json={"message": message}).status_code == 200


@pytest.mark.parametrize("body", [
    {}, {"message": None}, {"message": 42}, {"message": []}, {"message": ""},
    {"message": " \n \t "}, {"message": "x" * 501},
    {"message": "Explain", "history": None}, {"message": "Explain", "history": "bad"},
    {"message": "Explain", "history": [{"role": "user", "text": "x"}] * 7},
    *({"message": "Explain", "history": [turn]} for turn in [
        {}, {"role": "system", "text": "x"}, {"role": "assistant", "text": "x"},
        {"role": "user", "text": "x" * 1201}, {"role": "user", "text": None},
        {"role": "model", "text": 42},
    ]),
])
def test_invalid_body_is_422_without_model_calls_or_state_changes(api, body):
    client, state, chat = api
    response = client.post(path(state["id"]), json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert chat.calls == []
    assert client.get(f"/imports/{state['id']}").json() == state


@pytest.mark.parametrize("session_id,question_id,code", [
    ("missing", "currency", "session_not_found"),
    (None, "unknown", "question_not_found"),
    (None, "units_per_pack", "question_not_found"),
])
def test_unknown_session_or_unasked_question_is_404(api, session_id, question_id, code):
    client, state, chat = api
    response = client.post(path(session_id or state["id"], question_id), json={"message": "Explain"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == code
    assert chat.calls == []
    assert client.get(f"/imports/{state['id']}").json() == state


def test_answered_and_approved_questions_remain_askable(api):
    client, state, _ = api
    session_id = state["id"]
    assert answer(client, session_id, "price_includes_vat", "yes").status_code == 200
    assert answer(client, session_id, "currency", "ARS").status_code == 200
    approved = client.post(f"/imports/{session_id}/approve")
    assert approved.status_code == 200
    before = approved.json()
    response = client.post(path(session_id), json={"message": "What did I confirm?"})
    assert response.status_code == 200
    assert client.get(f"/imports/{session_id}").json() == before


@pytest.mark.parametrize("error", [ModelUnavailableError, ModelTimeoutError, ModelInvalidJsonError])
def test_model_failures_are_503_and_question_stays_answerable(api, error):
    client, state, chat = api
    chat.error = error("Gemma cannot answer")
    response = client.post(path(state["id"]), json={"message": "Explain"})
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "model_unavailable", "message": "Gemma cannot answer"}}
    assert client.get(f"/imports/{state['id']}").json() == state
    assert answer(client, state["id"], "price_includes_vat", "yes").status_code == 200


@pytest.mark.parametrize("content", [
    {"reply": "Check VAT", "suggested_option": "maybe"},
    {"reply": "", "suggested_option": None},
    {"reply": "x" * 1201, "suggested_option": None},
])
def test_invalid_model_reply_is_503_without_changing_the_import(api, content):
    client, state, chat = api
    chat.content = content
    response = client.post(path(state["id"]), json={"message": "Explain"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert client.get(f"/imports/{state['id']}").json() == state


def test_unconfigured_model_helper_uses_503_envelope(api):
    _, state, _ = api
    # The dependency is optional for applications that only use the deterministic flow.
    class Imports:
        def get(self, session_id):
            from types import SimpleNamespace
            from pricor.application.questions import question_for
            from pricor.ports.plan_advisor import ParameterId
            return SimpleNamespace(questions=(question_for(ParameterId.CURRENCY),), answers={})
    client = TestClient(create_app(ApiDependencies(Imports())), raise_server_exceptions=False)
    response = client.post(path(state["id"], "currency"), json={"message": "Explain"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
