from dataclasses import replace

import pytest

from pricor.application.manage_memory import InvalidMemoryTextError, ManageMemory
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
    return ManageMemory(store, embedder), store, embedder


def test_create_user_note_trims_and_embeds_explicit_text(managed):
    use_case, store, embedder = managed

    created = use_case.create_note("  VAT is included  ", supplier_name="Acme")

    assert created.text == "VAT is included"
    assert created.supplier_name == "Acme"
    assert created.source == "user_note"
    assert created.created_at == created.updated_at
    assert store.get(created.id) == created
    assert embedder.calls == [["VAT is included"]]


def test_create_from_an_explicitly_accepted_suggestion_sets_its_source(managed):
    use_case, store, _ = managed

    created = use_case.create_accepted_suggestion("Acme: VAT? -> Included", "Acme")

    assert created.source == "accepted_suggestion"
    assert store.get(created.id) == created


@pytest.mark.parametrize("text", ["", "  \n\t  ", "x" * 1001])
def test_create_rejects_empty_or_over_1000_character_notes(managed, text):
    use_case, store, embedder = managed

    with pytest.raises(InvalidMemoryTextError):
        use_case.create_note(text)

    assert store.items == {}
    assert embedder.calls == []


def test_edit_re_embeds_the_trimmed_text_and_preserves_identity(managed):
    use_case, store, embedder = managed
    created = use_case.create_note("old", "Acme")

    changed = use_case.edit(created.id, "  replacement  ")

    assert changed == replace(created, text="replacement", updated_at=changed.updated_at)
    assert changed.updated_at >= created.updated_at
    assert store.vectors[created.id] == [11.0, 1.0]
    assert embedder.calls == [["old"], ["replacement"]]


@pytest.mark.parametrize("text", [" ", "x" * 1001])
def test_edit_uses_the_same_note_validation(managed, text):
    use_case, store, embedder = managed
    created = use_case.create_note("old")

    with pytest.raises(InvalidMemoryTextError):
        use_case.edit(created.id, text)

    assert store.get(created.id).text == "old"
    assert embedder.calls == [["old"]]


def test_list_delete_and_unknown_id_are_exposed(managed):
    use_case, _, _ = managed
    created = use_case.create_note("temporary")

    assert use_case.list() == [created]
    use_case.delete(created.id)
    assert use_case.list() == []
    with pytest.raises(MemoryNotFoundError):
        use_case.delete(created.id)


def test_relevant_embeds_the_query_and_uses_k(managed):
    use_case, _, embedder = managed
    first = use_case.create_note("first")
    use_case.create_note("second")

    assert use_case.relevant("  supplier headers  ", 1) == [first]
    assert embedder.calls[-1] == ["supplier headers"]

