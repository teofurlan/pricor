from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.application.ask_about_question import AskAboutQuestion
from pricor.application.cascade import ClassifierStage
from pricor.application.errors import InvalidInputError, QuestionNotFoundError
from pricor.application.import_first_time import ImportFirstTime
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.model_errors import ModelUnavailableError
from pricor.ports.plan_advisor import ParameterId
from pricor.ports.question_helper import QuestionReply, QuestionTurn

from .fakes import FakeClassifier, FakeReader


class FakeHelper:
    def __init__(self):
        self.calls = []

    def ask(self, context, message, history=()):
        self.calls.append((context, message, history))
        return QuestionReply("Only confirm VAT if your supplier states it.", "no")


@pytest.fixture
def setup():
    rows = [
        ["Code", "Description", "Price", "VAT", "Stock"],
        ["A1", "Bolt", "121,00", "21%", "7"],
        ["A2", "Nut", "242,00", "21%", "8"],
        ["A3", "Screw", "363,00", "21%", "9"],
    ]
    table = {header: (role, 0.99) for header, role in zip(rows[0], [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.VAT_RATE, R.IGNORE])}
    imports = ImportFirstTime(FakeReader(rows), InMemoryImportSessionRepository(), [ClassifierStage("fake", FakeClassifier(table))])
    session = imports.start(Path("list.csv"), "Supplier", language="es")
    helper = FakeHelper()
    return imports, session, helper, AskAboutQuestion(imports.get, helper)


def test_read_only_grounded_question_context_and_trimmed_message(setup):
    imports, session, helper, use_case = setup
    before = deepcopy(session)
    history = (QuestionTurn("user", "What is VAT?"), QuestionTurn("model", "A tax."))
    reply = use_case.execute(session.id, "price_includes_vat", "  Explain this  ", history)
    assert reply == QuestionReply("Only confirm VAT if your supplier states it.", "no")
    context, message, sent_history = helper.calls[0]
    assert message == "Explain this" and sent_history == history
    assert context.supplier_name == "Supplier" and context.language == "es"
    assert context.question == next(q for q in session.questions if q.id.value == "price_includes_vat")
    assert {column.raw_header for column in context.columns} == {"Price", "VAT"}
    assert all(column.samples for column in context.columns)
    assert imports.get(session.id) == before


def test_answered_question_is_available_without_mutating_plan_or_session(setup):
    imports, session, helper, use_case = setup
    original = next(q for q in session.questions if q.id.value == "price_includes_vat")
    imports.answer(session.id, "price_includes_vat", "yes")
    imports.answer(session.id, "currency", "ARS")
    before = deepcopy(imports.get(session.id))
    use_case.execute(session.id, "price_includes_vat", "Explain my answer")
    context = helper.calls[0][0]
    assert context.question.id == original.id
    assert context.question.options == original.options
    assert context.question.reason == original.reason
    assert imports.get(session.id) == before
    assert imports.get(session.id).plan is not None


@pytest.mark.parametrize("question_id", ["not_a_question", "units_per_pack"])
def test_only_questions_asked_in_the_session_are_available(setup, question_id):
    _, session, helper, use_case = setup
    before = deepcopy(session)
    with pytest.raises(QuestionNotFoundError):
        use_case.execute(session.id, question_id, "Explain")
    assert helper.calls == [] and session == before


def test_unknown_session_propagates_not_found(setup):
    _, _, helper, use_case = setup
    with pytest.raises(SessionNotFoundError):
        use_case.execute("missing", "currency", "Explain")
    assert helper.calls == []


@pytest.mark.parametrize("message,history", [
    (" ", ()), ("x" * 501, ()),
    ("Explain", (QuestionTurn("user", "x"),) * 7),
    ("Explain", (QuestionTurn("system", "x"),)),
    ("Explain", (QuestionTurn("user", "x" * 1201),)),
])
def test_invalid_input_never_calls_model_or_mutates_session(setup, message, history):
    _, session, helper, use_case = setup
    before = deepcopy(session)
    with pytest.raises(InvalidInputError):
        use_case.execute(session.id, "currency", message, history)
    assert helper.calls == [] and session == before


def test_unconfigured_helper_preserves_question_answerability(setup):
    imports, session, _, _ = setup
    before = deepcopy(session)
    with pytest.raises(ModelUnavailableError):
        AskAboutQuestion(imports.get, None).execute(session.id, "currency", "Explain")
    assert imports.get(session.id) == before
    assert imports.answer(session.id, "currency", "ARS").answers[ParameterId.CURRENCY] == "ARS"


def test_context_is_detached_from_mutable_question_suggestion(setup):
    _, session, helper, use_case = setup
    from pricor.ports.question_model import Suggestion
    session.questions = tuple(replace(q, suggestion=Suggestion("no", 0.5, memory_ids=["memory-1"])) for q in session.questions)
    use_case.execute(session.id, "currency", "Explain")
    helper.calls[0][0].question.suggestion.memory_ids.append("not-stored")
    assert session.questions[0].suggestion.memory_ids == ["memory-1"]
