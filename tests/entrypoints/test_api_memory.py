from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pricor.application.manage_memory import ManageMemory
from pricor.entrypoints.api import ApiDependencies, _question, create_app
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.memory import MemoryNotFoundError
from pricor.ports.model_errors import ModelUnavailableError
from pricor.ports.plan_advisor import ParameterHypothesis, ParameterId, PlanProposal
from pricor.ports.question_model import LocalizedText, Option, Question, Suggestion


class FakeImports:
    def __init__(self):
        self.sessions = {}

    def get(self, session_id):
        try:
            return self.sessions[session_id]
        except KeyError as error:
            raise SessionNotFoundError(f"no session {session_id!r}") from error


class FakeStore:
    def __init__(self):
        self.items = {}

    def add(self, memory, embedding):
        self.items[memory.id] = memory

    def get(self, memory_id):
        try:
            return self.items[memory_id]
        except KeyError as error:
            raise MemoryNotFoundError(f"no memory {memory_id!r}") from error

    def list(self):
        return list(self.items.values())

    def update(self, memory, embedding):
        self.get(memory.id)
        self.items[memory.id] = memory

    def delete(self, memory_id):
        self.get(memory_id)
        del self.items[memory_id]

    def search(self, vector, k):
        return list(self.items.values())[:k]


class FakeEmbedder:
    def embed(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


def question(suggestion=Suggestion("yes", 0.9, suggested_by="gemma")):
    return Question(
        ParameterId.PRICE_INCLUDES_VAT,
        LocalizedText("Do prices include VAT?", "¿Los precios incluyen IVA?"),
        (
            Option("yes", LocalizedText("Yes, VAT is included", "Sí, incluyen IVA")),
            Option("no", LocalizedText("No, prices are net", "No, son precios netos")),
        ),
        "required",
        suggestion=suggestion,
    )


def test_question_json_exposes_suggestion_memory_ids():
    body = _question(
        question(Suggestion("yes", 0.9, suggested_by="gemma", memory_ids=["memory-1"]))
    )

    assert body["suggestion"]["memory_ids"] == ["memory-1"]


@pytest.fixture
def api():
    imports = FakeImports()
    store = FakeStore()
    memory = ManageMemory(store, FakeEmbedder(), imports.get)
    client = TestClient(create_app(ApiDependencies(imports, memory=memory)), raise_server_exceptions=False)
    return client, imports, store


def test_note_crud_and_memory_serialization(api):
    client, _, _ = api

    created = client.post("/memories", json={"text": "  VAT is included  ", "supplier_name": "Acme"})

    assert created.status_code == 201
    body = created.json()
    assert body["text"] == "VAT is included"
    assert body["supplier_name"] == "Acme"
    assert body["source"] == "user_note"
    assert body["created_at"] == body["updated_at"]
    assert client.get("/memories").json() == [body]

    edited = client.patch(f"/memories/{body['id']}", json={"text": "replacement"})
    assert edited.status_code == 200
    assert edited.json()["text"] == "replacement"
    assert edited.json()["created_at"] == body["created_at"]

    deleted = client.delete(f"/memories/{body['id']}")
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get("/memories").json() == []


@pytest.mark.parametrize("method,path", [("patch", "/memories/missing"), ("delete", "/memories/missing")])
def test_unknown_memory_ids_are_404(api, method, path):
    client, _, _ = api
    response = (
        client.patch(path, json={"text": "replacement"})
        if method == "patch"
        else client.delete(path)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "memory_not_found"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"supplier_name": "Acme"},
        {"session_id": "s"},
        {"text": "note", "question_id": "currency"},
        {"text": "note", "session_id": "s", "question_id": "currency"},
    ],
)
def test_post_accepts_only_one_of_the_two_documented_shapes(api, payload):
    response = api[0].post("/memories", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "x" * 1001}])
def test_invalid_memory_text_is_422(api, payload):
    response = api[0].post("/memories", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_memory_text"


def test_an_accepted_gemma_suggestion_uses_the_session_and_exact_english_text(api):
    client, imports, _ = api
    item = question()
    imports.sessions["s1"] = SimpleNamespace(
        supplier_name="Acme",
        questions=(),
        answers={item.id: "yes"},
        proposal=PlanProposal((ParameterHypothesis(item.id, True, 0.9, ()),), ()),
    )

    response = client.post(
        "/memories", json={"session_id": "s1", "question_id": "price_includes_vat"}
    )

    assert response.status_code == 201
    assert (
        response.json()["text"]
        == "Acme: Do the prices in this list already include VAT? -> Yes, VAT is included"
    )
    assert response.json()["source"] == "accepted_suggestion"


@pytest.mark.parametrize(
    ("suggestion", "answer"),
    [
        (Suggestion("yes", 0.9, suggested_by="heuristics"), "yes"),
        (Suggestion("yes", 0.9, suggested_by="gemma"), "no"),
        (None, "yes"),
    ],
)
def test_rejected_accepted_suggestion_rules_are_409(api, suggestion, answer):
    client, imports, _ = api
    item = question(suggestion)
    imports.sessions["s1"] = SimpleNamespace(
        supplier_name="Acme", questions=(item,), answers={item.id: answer}
    )

    response = client.post(
        "/memories", json={"session_id": "s1", "question_id": "price_includes_vat"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "accepted_suggestion_conflict"


@pytest.mark.parametrize(
    ("session_id", "question_id", "code"),
    [("missing", "price_includes_vat", "session_not_found"), ("s1", "missing", "question_not_found")],
)
def test_unknown_session_or_question_is_404(api, session_id, question_id, code):
    client, imports, _ = api
    imports.sessions["s1"] = SimpleNamespace(supplier_name="Acme", questions=(), answers={})

    response = client.post(
        "/memories", json={"session_id": session_id, "question_id": question_id}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == code


def test_unconfigured_memory_is_503():
    client = TestClient(create_app(ApiDependencies(FakeImports())), raise_server_exceptions=False)

    response = client.get("/memories")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "memory_unavailable", "message": "semantic memory is not configured"}
    }


def test_embedder_unavailability_is_503_with_a_clear_message():
    class OfflineEmbedder:
        def embed(self, texts):
            raise ModelUnavailableError("cannot reach the embedding model server")

    imports = FakeImports()
    memory = ManageMemory(FakeStore(), OfflineEmbedder(), imports.get)
    client = TestClient(create_app(ApiDependencies(imports, memory=memory)), raise_server_exceptions=False)

    response = client.post("/memories", json={"text": "remember this"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "embedder_unavailable",
            "message": "cannot reach the embedding model server",
        }
    }
