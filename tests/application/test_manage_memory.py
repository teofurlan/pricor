from dataclasses import replace
from types import SimpleNamespace

import pytest

from pricor.application.errors import AcceptedSuggestionConflictError, QuestionNotFoundError
from pricor.application.manage_memory import InvalidMemoryTextError, ManageMemory
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.plan_advisor import ParameterHypothesis, ParameterId, PlanProposal
from pricor.ports.question_model import LocalizedText, Option, Question, Suggestion
from pricor.ports.memory import MemoryNotFoundError


class FakeEmbedder:
    model = "test-model"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[float(len(text)), 1.0] for text in texts]


class FakeStore:
    def __init__(self):
        self.items = {}
        self.vectors = {}

    def add(self, memory, embedding):
        self.items[memory.id] = memory
        self.vectors[memory.id] = embedding

    def get(self, memory_id):
        try:
            return self.items[memory_id]
        except KeyError as error:
            raise MemoryNotFoundError(memory_id) from error

    def list(self):
        return list(self.items.values())

    def update(self, memory, embedding):
        self.get(memory.id)
        self.items[memory.id] = memory
        self.vectors[memory.id] = embedding

    def delete(self, memory_id):
        self.get(memory_id)
        del self.items[memory_id]
        del self.vectors[memory_id]

    def search(self, vector, k):
        return list(self.items.values())[:k]


@pytest.fixture
def managed():
    embedder = FakeEmbedder()
    store = FakeStore()
    sessions = {}

    def get_session(session_id):
        try:
            return sessions[session_id]
        except KeyError as error:
            raise SessionNotFoundError(session_id) from error

    return ManageMemory(store, embedder, get_session), store, embedder, sessions


def test_create_user_note_trims_and_embeds_explicit_text(managed):
    use_case, store, embedder, _ = managed

    created = use_case.create_note("  VAT is included  ", supplier_name="Acme")

    assert created.text == "VAT is included"
    assert created.supplier_name == "Acme"
    assert created.source == "user_note"
    assert created.created_at == created.updated_at
    assert store.get(created.id) == created
    assert embedder.calls == [["VAT is included"]]


def test_create_from_an_accepted_gemma_suggestion_builds_deterministic_english_text(managed):
    use_case, store, embedder, sessions = managed
    question = Question(
        ParameterId.PRICE_INCLUDES_VAT,
        LocalizedText("Do prices include VAT?", "¿Los precios incluyen IVA?"),
        (
            Option("yes", LocalizedText("Yes, VAT is included", "Sí, incluyen IVA")),
            Option("no", LocalizedText("No, prices are net", "No, son precios netos")),
        ),
        "required",
        suggestion=Suggestion("yes", 0.8, suggested_by="gemma"),
    )
    sessions["session-1"] = SimpleNamespace(
        supplier_name="Acme",
        questions=(),
        answers={question.id: "yes"},
        proposal=PlanProposal(
            (ParameterHypothesis(question.id, True, 0.8, ()),), ()
        ),
    )

    created = use_case.create_accepted_suggestion("session-1", "price_includes_vat")

    assert (
        created.text
        == "Acme: Do the prices in this list already include VAT? -> Yes, VAT is included"
    )
    assert created.supplier_name == "Acme"
    assert created.source == "accepted_suggestion"
    assert store.get(created.id) == created
    assert embedder.calls == [[created.text]]


@pytest.mark.parametrize(
    ("suggestion", "answer"),
    [
        (Suggestion("yes", 0.8, suggested_by="heuristics"), "yes"),
        (Suggestion("yes", 0.8, suggested_by="gemma"), "no"),
        (None, "yes"),
    ],
)
def test_accepted_suggestion_requires_an_answer_matching_a_gemma_suggestion(
    managed, suggestion, answer
):
    use_case, store, embedder, sessions = managed
    question = Question(
        ParameterId.PRICE_INCLUDES_VAT,
        LocalizedText("Do prices include VAT?", "¿Los precios incluyen IVA?"),
        (Option("yes", LocalizedText("Yes", "Sí")), Option("no", LocalizedText("No", "No"))),
        "required",
        suggestion=suggestion,
    )
    sessions["session-1"] = SimpleNamespace(
        supplier_name="Acme", questions=(question,), answers={question.id: answer}
    )

    with pytest.raises(AcceptedSuggestionConflictError):
        use_case.create_accepted_suggestion("session-1", "price_includes_vat")

    assert store.items == {}
    assert embedder.calls == []


def test_accepted_suggestion_rejects_an_unknown_question(managed):
    use_case, store, embedder, sessions = managed
    sessions["session-1"] = SimpleNamespace(supplier_name="Acme", questions=(), answers={})

    with pytest.raises(QuestionNotFoundError):
        use_case.create_accepted_suggestion("session-1", "missing")

    assert store.items == {}
    assert embedder.calls == []


@pytest.mark.parametrize("text", ["", "  \n\t  ", "x" * 1001])
def test_create_rejects_empty_or_over_1000_character_notes(managed, text):
    use_case, store, embedder, _ = managed

    with pytest.raises(InvalidMemoryTextError):
        use_case.create_note(text)

    assert store.items == {}
    assert embedder.calls == []


def test_edit_re_embeds_the_trimmed_text_and_preserves_identity(managed):
    use_case, store, embedder, _ = managed
    created = use_case.create_note("old", "Acme")

    changed = use_case.edit(created.id, "  replacement  ")

    assert changed == replace(created, text="replacement", updated_at=changed.updated_at)
    assert changed.updated_at >= created.updated_at
    assert store.vectors[created.id] == [11.0, 1.0]
    assert embedder.calls == [["old"], ["replacement"]]


@pytest.mark.parametrize("text", [" ", "x" * 1001])
def test_edit_uses_the_same_note_validation(managed, text):
    use_case, store, embedder, _ = managed
    created = use_case.create_note("old")

    with pytest.raises(InvalidMemoryTextError):
        use_case.edit(created.id, text)

    assert store.get(created.id).text == "old"
    assert embedder.calls == [["old"]]


def test_list_delete_and_unknown_id_are_exposed(managed):
    use_case, _, _, _ = managed
    created = use_case.create_note("temporary")

    assert use_case.list() == [created]
    use_case.delete(created.id)
    assert use_case.list() == []
    with pytest.raises(MemoryNotFoundError):
        use_case.delete(created.id)


def test_relevant_embeds_the_query_and_uses_k(managed):
    use_case, _, embedder, _ = managed
    first = use_case.create_note("first")
    use_case.create_note("second")

    assert use_case.relevant("  supplier headers  ", 1) == [first]
    assert embedder.calls[-1] == ["supplier headers"]
