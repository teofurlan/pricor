"""A currency column is read, proposed and confirmed by the user; nothing is applied silently."""

import json
from datetime import UTC, datetime
from itertools import count

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.errors import InvalidInputError
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session import SessionStatus

from .fakes import FakeClassifier, FakeReader

ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Moneda": (R.CURRENCY, 0.95),
    "Precio": (R.COST_PRICE, 0.9),
}
HEADER = ["Codigo", "Descripcion", "Moneda", "Precio"]
WEEK1 = [
    HEADER,
    ["A1", "Antenna", "$", "1846"],
    ["A2", "Mini antenna", "u$s", "2.50"],
    ["A3", "Cable", "$", "10"],
]
WEEK2_NEW_VALUE = [*WEEK1, ["A4", "Switch", "guaranies", "5"]]
DETECTED_TOKEN = 'map:{"$":"ARS","u$s":"USD"}'


class Harness:
    def __init__(self):
        self.reader = FakeReader(WEEK1)
        self.database = SqliteDatabase(":memory:")
        ids = (f"s{n}" for n in count(1))
        clock = iter(datetime(2026, 10, day, tzinfo=UTC) for day in range(1, 29))
        self.use_case = ReuseSupplierPlan(
            self.reader,
            self.database.sessions,
            [ClassifierStage("heuristics", FakeClassifier(ROLES))],
            plans=self.database.plans,
            approvals=self.database,
            id_factory=lambda: next(ids),
            clock=lambda: next(clock),
        )

    def start(self, rows=WEEK1):
        self.reader.rows = tuple(tuple(row) for row in rows)
        return self.use_case.start("lista.xlsx", "Emilio")

    def answer(self, session, **answers):
        for question_id, option in answers.items():
            self.use_case.answer(session.id, question_id, option)
        return self.use_case.get(session.id)


@pytest.fixture
def harness():
    harness = Harness()
    yield harness
    harness.database.close()


def question(session, question_id):
    return next((q for q in session.questions if q.id.value == question_id), None)


def test_a_recognized_currency_column_is_a_question_with_a_labeled_suggestion(harness):
    session = harness.start()

    asked = question(session, "currency")
    assert asked is not None
    assert session.status is SessionStatus.QUESTIONS_PENDING
    assert session.plan is None
    assert "currency" not in {parameter.value for parameter in session.answers}
    assert asked.suggestion.option == DETECTED_TOKEN
    assert asked.suggestion.suggested_by == "detected"
    label = next(o.label for o in asked.options if o.token == DETECTED_TOKEN)
    assert label.en == "Detected: `$` → ARS, `u$s` → USD"
    assert label.es == "Detectado: `$` → ARS, `u$s` → USD"


def test_confirming_the_suggestion_builds_the_plan_with_that_map(harness):
    session = harness.start()

    session = harness.answer(session, price_includes_vat="no", currency=DETECTED_TOKEN, fx_conversion="keep")

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    step = next(s for s in session.plan.steps if s.op.value == "map_values")
    assert dict(step.table) == {"$": "ARS", "u$s": "USD"}
    page = harness.use_case.preview(session.id)
    assert {item.record["supplier_code"]: item.record["currency"] for item in page.items} == {
        "A1": "ARS",
        "A2": "USD",
        "A3": "ARS",
    }


def test_the_user_may_edit_the_map_instead_of_accepting_it(harness):
    session = harness.start()
    edited = 'map:{"$":"ARS","u$s":"EUR"}'

    session = harness.answer(session, price_includes_vat="no", currency=edited, fx_conversion="keep")

    step = next(s for s in session.plan.steps if s.op.value == "map_values")
    assert dict(step.table) == {"$": "ARS", "u$s": "EUR"}


@pytest.mark.parametrize(
    "token",
    ["map:", "map:{}", "map:not json", 'map:{"$":"XYZ"}', 'map:{"$":1}', 'map:["$"]', "map:{\"\":\"ARS\"}"],
)
def test_a_malformed_map_is_refused(harness, token):
    session = harness.start()

    with pytest.raises(InvalidInputError):
        harness.use_case.answer(session.id, "currency", token)


def test_an_unrecognized_value_gets_a_question_without_a_suggestion(harness):
    session = harness.start([*WEEK1, ["A4", "Switch", "guaranies", "5"]])

    asked = question(session, "currency")
    assert asked.suggestion is None
    assert not any(option.token.startswith("map:") for option in asked.options)


def test_a_model_hypothesis_does_not_replace_the_detected_suggestion(harness):
    from pricor.domain.plan_builder import ConstantSource
    from pricor.ports.plan_advisor import ParameterHypothesis, ParameterId, PlanProposal

    from .fakes import FakeAdvisor

    harness.use_case._advisor = FakeAdvisor(
        PlanProposal((ParameterHypothesis(ParameterId.CURRENCY, ConstantSource("USD"), 0.9),), ())
    )
    session = harness.start()

    assert question(session, "currency").suggestion.option == DETECTED_TOKEN


def test_reuse_keeps_the_confirmed_map_without_asking_again(harness):
    first = harness.start()
    harness.answer(first, price_includes_vat="no", currency=DETECTED_TOKEN, fx_conversion="keep")
    harness.use_case.approve(first.id)

    session = harness.start()

    assert session.mode == "reuse"
    assert session.questions == ()
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert {key.value: token for key, token in session.answers.items()}["currency"] == DETECTED_TOKEN


def test_reuse_asks_again_when_the_new_file_has_a_value_the_map_misses(harness):
    first = harness.start()
    harness.answer(first, price_includes_vat="no", currency=DETECTED_TOKEN, fx_conversion="keep")
    harness.use_case.approve(first.id)

    session = harness.start(WEEK2_NEW_VALUE)

    asked = question(session, "currency")
    assert asked is not None and asked.suggestion is None
    assert "guaranies" in asked.reason


def test_the_confirmed_map_is_stored_with_the_plan_confirmations(harness):
    session = harness.start()
    session = harness.answer(session, price_includes_vat="no", currency=DETECTED_TOKEN, fx_conversion="keep")

    stored = [text for text in session.plan.confirmations if text.startswith("currency=")]
    assert stored == [f"currency={DETECTED_TOKEN} (user)"]
    assert json.loads(stored[0].split("=", 1)[1].removeprefix("map:").removesuffix(" (user)")) == {
        "$": "ARS",
        "u$s": "USD",
    }
