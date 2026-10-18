from types import SimpleNamespace

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.application.import_first_time import ClassifierStage, ImportFirstTime
from pricor.application.manage_memory import ManageMemory
from pricor.ports.model_errors import ModelUnavailableError
from pricor.ports.plan_advisor import ParameterHypothesis, ParameterId, PlanProposal

from .fakes import FakeAdvisor, FakeClassifier, FakeReader
from .test_import_first_time import HEADER, ROLES, ROWS


class FakeMemory:
    def __init__(self, items=(), error=None):
        self.items = list(items)
        self.error = error
        self.calls = []

    def relevant(self, query, k):
        self.calls.append((query, k))
        if self.error is not None:
            raise self.error
        return self.items[:k]


class RecordingAdvisor(FakeAdvisor):
    def __init__(self, proposal):
        super().__init__(proposal)
        self.memory_contexts = []

    def propose(self, sheet, classifications, memory_context=None, language="en"):
        self.memory_contexts.append(memory_context)
        return super().propose(sheet, classifications, memory_context, language)


class OfflineEmbedder:
    def embed(self, texts):
        raise ModelUnavailableError("embedding service is down")


class UnusedStore:
    def search(self, vector, k):
        raise AssertionError("search must not run without an embedding")


def make(memory, advisor):
    repository = InMemoryImportSessionRepository()
    use_case = ImportFirstTime(
        FakeReader(ROWS),
        repository,
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
        advisor,
        id_factory=iter("abcdef").__next__,
        memory=memory,
        memory_top_k=2,
    )
    return use_case


def test_relevant_memories_use_supplier_and_normalized_headers_and_map_refs_to_ids():
    memories = [
        SimpleNamespace(id="memory-a", text="VAT is included"),
        SimpleNamespace(id="memory-b", text="Prices are per unit"),
    ]
    memory = FakeMemory(memories)
    hypothesis = ParameterHypothesis(
        ParameterId.PRICE_INCLUDES_VAT, True, 0.8, memory_refs=(2, 1)
    )
    advisor = RecordingAdvisor(PlanProposal((hypothesis,), ()))

    session = make(memory, advisor).start("lista.xlsx", "Ferreteria Ejemplo")

    assert memory.calls == [
        ("Ferreteria Ejemplo codigo descripcion precio lista iva", 2)
    ]
    assert advisor.memory_contexts == [["VAT is included", "Prices are per unit"]]
    question = next(item for item in session.questions if item.id is ParameterId.PRICE_INCLUDES_VAT)
    assert question.suggestion.memory_ids == ["memory-b", "memory-a"]


def test_memory_failure_falls_back_to_gemma_and_records_a_notice():
    memory = ManageMemory(UnusedStore(), OfflineEmbedder(), lambda _: None)
    hypothesis = ParameterHypothesis(ParameterId.PRICE_INCLUDES_VAT, True, 0.8)
    advisor = FakeAdvisor(PlanProposal((hypothesis,), ()))

    session = make(memory, advisor).start("lista.xlsx", "Ferreteria Ejemplo")

    assert [notice.code for notice in session.notices] == ["memory_unavailable"]
    assert advisor.calls == 1
    question = next(item for item in session.questions if item.id is ParameterId.PRICE_INCLUDES_VAT)
    assert question.suggestion.option == "yes"
