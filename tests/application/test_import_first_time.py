from decimal import Decimal

import pytest

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.application.errors import (
    InvalidInputError,
    InvalidOperationError,
    NoAcceptedRowsError,
)
from pricor.application.import_first_time import (
    UNCALIBRATED_THRESHOLD,
    ClassifierStage,
    ImportFirstTime,
)
from pricor.application.import_session import SessionStatus
from pricor.domain.plan_builder import ConstantSource
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.model_errors import ModelSchemaError, ModelTimeoutError, ModelUnavailableError
from pricor.ports.plan_advisor import (
    Evidence,
    ParameterHypothesis,
    ParameterId,
    PlanProposal,
    PlanQuestion,
    QuestionOption,
)

from .fakes import FakeAdvisor, FakeClassifier, FakeReader

HEADER = ("Codigo", "Descripcion", "Precio lista", "IVA")
ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Precio lista": (R.COST_PRICE, 0.9),
    "IVA": (R.VAT_RATE, 0.9),
}
ROWS = [
    ("LISTA OCTUBRE", None, None, None),  # file row 1: preamble
    HEADER,  # file row 2
    ("A1", "Tornillo", "1.210,00", "21%"),  # file row 3
    ("A2", "Tuerca", "968,00", "21%"),  # file row 4
    ("A3", "Arandela", "121,00", "21%"),  # file row 5
    ("A4", "Clavo", "60,50", "21%"),  # file row 6
    ("A5", "Taco", "1.815,00", "21%"),  # file row 7
    ("A6", "Brida", "abc", "21%"),  # file row 8: rejected
    (None, None, None, None),  # file row 9: empty
    ("TOTAL", None, "4.174,50", None),  # file row 10: total
]


def make(rows=ROWS, stages=None, advisor=None, reader=None):
    reader = reader or FakeReader(rows)
    if stages is None:
        stages = [ClassifierStage("heuristics", FakeClassifier(ROLES))]
    repository = InMemoryImportSessionRepository()
    use_case = ImportFirstTime(
        reader, repository, stages, advisor, id_factory=iter("abcdef").__next__
    )
    return use_case, repository


def start(use_case, **kwargs):
    return use_case.start("lista.xlsx", "Ferreteria Ejemplo", **kwargs)


def question_ids(session):
    return [question.id.value for question in session.questions]


def proposal(hypotheses=(), questions=()):
    return PlanProposal(tuple(hypotheses), tuple(questions), latency_seconds=1.0)


def answer_all(use_case, session_id, **choices):
    values = {"price_includes_vat": "yes", "currency": "ARS", **choices}
    for question_id, option in values.items():
        use_case.answer(session_id, question_id, option)


# -- happy path --


def test_full_happy_path_to_approval():
    use_case, _ = make()
    session = start(use_case)
    assert session.status is SessionStatus.QUESTIONS_PENDING
    assert sorted(question_ids(session)) == ["currency", "price_includes_vat"]
    assert session.plan is None

    answer_all(use_case, session.id)
    session = use_case.get(session.id)
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.plan is not None
    assert any("price_includes_vat=yes" in text for text in session.plan.confirmations)

    page = use_case.preview(session.id)
    assert page.totals["accepted"] == 5
    assert page.totals["rejected"] == 1
    approved = use_case.approve(session.id)
    assert approved.status is SessionStatus.APPROVED
    assert approved.approved_plan is approved.plan
    assert len(approved.approved_result.accepted) == 5


def test_default_threshold_is_marked_uncalibrated():
    assert 0 < UNCALIBRATED_THRESHOLD < 1
    stage = ClassifierStage("heuristics", FakeClassifier())
    assert stage.threshold == UNCALIBRATED_THRESHOLD
    assert stage.threshold_calibrated is False
    with pytest.raises(ValueError):
        ClassifierStage("bad", FakeClassifier(), threshold=1.5)


def test_in_memory_repository_reports_unknown_sessions():
    use_case, repository = make()
    with pytest.raises(SessionNotFoundError):
        repository.get("missing")
    with pytest.raises(SessionNotFoundError):
        use_case.get("missing")


# -- header handling --


def test_headerless_sheet_requires_a_header_choice_then_uses_column_n():
    rows = [("A1", "Tornillo", "10,50"), ("A2", "Tuerca", "11,50")]
    stage = ClassifierStage("heuristics", FakeClassifier())
    use_case, _ = make(rows, [stage])
    session = start(use_case)
    assert session.status is SessionStatus.HEADER_CHOICE_REQUIRED
    assert [c.row_index for c in session.header_candidates] == [0, 1]
    assert session.columns == ()

    session = use_case.choose_header(session.id, None)
    assert session.profile.header_row is None
    assert [c.header for c in session.columns] == ["column_0", "column_1", "column_2"]
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED


def test_ambiguous_header_offers_candidates_and_applies_the_choice():
    rows = [
        ("Codigo", "Descripcion", "Precio"),
        ("Ref", "Nombre", "Importe"),
        ("A1", "Tornillo", "10,50"),
        ("A2", "Tuerca", "11,50"),
    ]
    classifier = FakeClassifier(
        {"Ref": (R.CODE, 0.9), "Nombre": (R.DESCRIPTION, 0.9), "Importe": (R.COST_PRICE, 0.9)}
    )
    use_case, _ = make(rows, [ClassifierStage("heuristics", classifier)])
    session = start(use_case)
    assert session.status is SessionStatus.HEADER_CHOICE_REQUIRED
    candidates = [c.row_index for c in session.header_candidates]
    assert 0 in candidates and 1 in candidates
    assert classifier.seen_indexes == []  # nothing is classified before the header is settled

    session = use_case.choose_header(session.id, 1)
    assert session.profile.header_row == 1
    assert [c.header for c in session.columns] == ["Ref", "Nombre", "Importe"]
    assert session.status is SessionStatus.QUESTIONS_PENDING


def test_invalid_header_choice_is_rejected():
    use_case, _ = make()
    session = start(use_case)
    with pytest.raises(InvalidInputError):
        use_case.choose_header(session.id, 99)


# -- cascade --


def test_cascade_attributes_each_column_to_the_stage_that_decided_it():
    first = FakeClassifier({"Codigo": (R.CODE, 0.95), "Precio lista": (R.COST_PRICE, 0.4)})
    second = FakeClassifier(ROLES)
    use_case, _ = make(
        stages=[ClassifierStage("heuristics", first), ClassifierStage("gemma", second)]
    )
    session = start(use_case)

    by_header = {column.header: column for column in session.columns}
    assert by_header["Codigo"].decided_by == "heuristics"
    assert by_header["Descripcion"].decided_by == "gemma"
    assert by_header["Precio lista"].decided_by == "gemma"
    assert by_header["Precio lista"].score == 0.9
    assert by_header["Precio lista"].rationale == "fake:Precio lista"
    # The later stage only sees the columns the earlier one did not settle.
    assert first.seen_indexes == [[0, 1, 2, 3]]
    assert second.seen_indexes == [[1, 2, 3]]
    stages_seen = [p.stage for p in by_header["Precio lista"].proposals]
    assert stages_seen == ["heuristics", "gemma"]


def test_columns_below_threshold_after_the_last_stage_need_user_confirmation():
    weak = FakeClassifier({"Codigo": (R.CODE, 0.95), "Precio lista": (R.COST_PRICE, 0.5)})
    use_case, _ = make(stages=[ClassifierStage("heuristics", weak)])
    session = start(use_case)
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED
    pending = [c for c in session.columns if c.role is None]
    assert {c.header for c in pending} == {"Descripcion", "Precio lista", "IVA"}
    assert next(c for c in pending if c.header == "Precio lista").proposals[0].role is R.COST_PRICE

    session = use_case.set_roles(session.id, {1: R.DESCRIPTION, 2: R.COST_PRICE, 3: R.VAT_RATE})
    assert session.columns[2].decided_by == "user"
    assert session.status is SessionStatus.QUESTIONS_PENDING


def test_set_roles_rejects_unknown_columns():
    use_case, _ = make()
    session = start(use_case)
    with pytest.raises(InvalidInputError):
        use_case.set_roles(session.id, {42: R.CODE})


# -- deterministic questions --


def test_questions_exist_even_when_the_advisor_returns_none():
    advisor = FakeAdvisor(proposal())
    use_case, _ = make(advisor=advisor)
    session = start(use_case)
    assert sorted(question_ids(session)) == ["currency", "price_includes_vat"]
    for question in session.questions:
        assert question.text.en and question.text.es
        assert all(option.label.en and option.label.es for option in question.options)
        assert question.suggestion is None
    assert advisor.calls == 1


def test_questions_work_without_any_advisor():
    use_case, _ = make(advisor=None)
    session = start(use_case)
    assert sorted(question_ids(session)) == ["currency", "price_includes_vat"]


def test_model_hypothesis_is_a_suggestion_and_is_never_applied():
    hypothesis = ParameterHypothesis(ParameterId.PRICE_INCLUDES_VAT, True, 0.8, (Evidence(3, "21%"),))
    use_case, _ = make(advisor=FakeAdvisor(proposal([hypothesis])))
    session = start(use_case)

    question = next(q for q in session.questions if q.id is ParameterId.PRICE_INCLUDES_VAT)
    assert question.suggestion.suggested_by == "model"
    assert question.suggestion.option == "yes"
    assert question.suggestion.confidence == 0.8
    assert question.suggestion.calibrated is False
    assert question.suggestion.evidence == (Evidence(3, "21%"),)
    assert session.status is SessionStatus.QUESTIONS_PENDING
    assert session.plan is None
    assert session.answers == {}


def test_suggestion_outside_the_closed_options_is_dropped():
    hypotheses = [
        ParameterHypothesis(ParameterId.CURRENCY, ConstantSource("ARS"), 0.9),
        ParameterHypothesis(ParameterId.DISCOUNTS, ConstantSource(()), 0.9),
    ]
    use_case, _ = make(advisor=FakeAdvisor(proposal(hypotheses)))
    session = start(use_case)
    currency = next(q for q in session.questions if q.id is ParameterId.CURRENCY)
    assert currency.suggestion.option == "ARS"
    assert "discounts" not in question_ids(session)


def test_model_phrasing_is_attached_to_the_matching_question_only():
    asked = PlanQuestion(
        ParameterId.PRICE_INCLUDES_VAT,
        "Do the prices already include VAT?",
        (QuestionOption("Yes", True), QuestionOption("No", False)),
    )
    use_case, _ = make(advisor=FakeAdvisor(proposal(questions=[asked])))
    session = start(use_case)
    by_id = {q.id: q for q in session.questions}
    vat = by_id[ParameterId.PRICE_INCLUDES_VAT]
    assert vat.model_phrasing == "Do the prices already include VAT?"
    assert by_id[ParameterId.CURRENCY].model_phrasing is None
    assert vat.options[0].token == "yes"  # the options stay deterministic


def test_answers_are_validated_against_the_closed_options():
    use_case, _ = make()
    session = start(use_case)
    with pytest.raises(InvalidInputError):
        use_case.answer(session.id, "price_includes_vat", "maybe")
    with pytest.raises(InvalidInputError):
        use_case.answer(session.id, "units_per_pack", "constant:12")  # not asked
    with pytest.raises(InvalidInputError):
        use_case.answer(session.id, "not_a_parameter", "yes")
    assert use_case.get(session.id).answers == {}


def test_numeric_questions_accept_a_custom_constant_but_only_valid_ones():
    rows = [HEADER[:3], ("A1", "Tornillo", "1.210,00"), ("A2", "Tuerca", "968,00")]
    use_case, _ = make(rows, [ClassifierStage("heuristics", FakeClassifier(ROLES))])
    session = start(use_case)
    use_case.answer(session.id, "price_includes_vat", "yes")
    session = use_case.get(session.id)
    assert "vat_rate" in question_ids(session)
    with pytest.raises(InvalidInputError):
        use_case.answer(session.id, "vat_rate", "constant:abc")
    with pytest.raises(InvalidInputError):
        use_case.answer(session.id, "vat_rate", "constant:250")
    use_case.answer(session.id, "vat_rate", "constant:10.5")
    use_case.answer(session.id, "currency", "USD")
    session = use_case.get(session.id)
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    first = use_case.preview(session.id).items[0]
    assert first.record["currency"] == "USD"
    assert Decimal(first.record["unit_cost_net"]) == Decimal("1095.02")  # 1210 / 1.105


def test_changing_an_answer_rebuilds_the_plan():
    use_case, _ = make()
    session = start(use_case)
    answer_all(use_case, session.id)
    before = use_case.preview(session.id).items[0].record["unit_cost_net"]
    use_case.answer(session.id, "price_includes_vat", "no")
    session = use_case.get(session.id)
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    after = use_case.preview(session.id).items[0].record["unit_cost_net"]
    assert before != after
    assert after == "1210.00"


# -- degradation --


def test_advisor_failure_keeps_the_deterministic_questions_and_records_a_notice():
    advisor = FakeAdvisor(error=ModelSchemaError("bad reply"))
    use_case, _ = make(advisor=advisor)
    session = start(use_case)
    assert [n.code for n in session.notices] == ["model_unavailable"]
    assert sorted(question_ids(session)) == ["currency", "price_includes_vat"]
    assert all(q.suggestion is None for q in session.questions)
    answer_all(use_case, session.id)
    assert use_case.get(session.id).status is SessionStatus.READY_FOR_PREVIEW
    assert advisor.calls == 1  # a failure is not retried on every answer


def test_model_stage_failure_sends_low_confidence_columns_to_the_user():
    first = FakeClassifier({"Codigo": (R.CODE, 0.95)})
    second = FakeClassifier(error=ModelUnavailableError("ollama is down"))
    advisor = FakeAdvisor(proposal())
    use_case, _ = make(
        stages=[ClassifierStage("heuristics", first), ClassifierStage("gemma", second)],
        advisor=advisor,
    )
    session = start(use_case)
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED
    assert [c.header for c in session.columns if c.role is None] == [
        "Descripcion",
        "Precio lista",
        "IVA",
    ]
    (notice,) = session.notices
    assert notice.code == "model_unavailable"
    assert notice.stage == "gemma"
    use_case.set_roles(session.id, {1: R.DESCRIPTION, 2: R.COST_PRICE, 3: R.VAT_RATE})
    session = use_case.get(session.id)
    assert sorted(question_ids(session)) == ["currency", "price_includes_vat"]
    assert advisor.calls == 0  # the server is unreachable: do not wait for it again
    assert [n.code for n in session.notices] == ["model_unavailable"]


def test_timeout_is_treated_like_unavailability():
    second = FakeClassifier(error=ModelTimeoutError("slow"))
    use_case, _ = make(
        stages=[ClassifierStage("heuristics", FakeClassifier()), ClassifierStage("gemma", second)]
    )
    session = start(use_case)
    assert [n.code for n in session.notices] == ["model_unavailable"]
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED


# -- preview and approval --


def test_preview_reports_file_row_numbers_traces_and_counts_that_add_up():
    use_case, _ = make()
    session = start(use_case)
    answer_all(use_case, session.id)
    page = use_case.preview(session.id)

    assert [(i.row_number, i.status) for i in page.items] == [
        (3, "accepted"),
        (4, "accepted"),
        (5, "accepted"),
        (6, "accepted"),
        (7, "accepted"),
        (8, "rejected"),
    ]
    first = page.items[0]
    assert first.original == ("A1", "Tornillo", "1.210,00", "21%")
    assert first.trace[0].step == "original"
    assert first.record["supplier_code"] == "A1"
    assert first.record["unit_cost_net"] == "1000.00"
    rejected = page.items[5]
    assert rejected.record is None
    assert rejected.reasons

    totals = page.totals
    assert totals["data_rows"] == 6
    assert totals["accepted"] + totals["rejected"] == totals["data_rows"]
    assert totals["rejected_rows"][0]["row_number"] == 8
    assert totals["rejected_rows"][0]["reasons"] == list(rejected.reasons)
    assert sum(totals["reason_counts"].values()) >= 1
    assert totals["skipped_rows"] == {"empty": 1, "total": 1, "section": 0, "preamble": 1}


def test_preview_is_paged():
    use_case, _ = make()
    session = start(use_case)
    answer_all(use_case, session.id)
    page = use_case.preview(session.id, offset=1, limit=1)
    assert [i.row_number for i in page.items] == [4]
    assert page.total_items == 6
    assert page.totals["accepted"] == 5  # totals always cover the whole sheet
    with pytest.raises(InvalidInputError):
        use_case.preview(session.id, offset=-1)
    with pytest.raises(InvalidInputError):
        use_case.preview(session.id, limit=0)


def test_preview_and_approve_need_a_ready_session():
    use_case, _ = make()
    session = start(use_case)
    with pytest.raises(InvalidOperationError):
        use_case.preview(session.id)
    with pytest.raises(InvalidOperationError):
        use_case.approve(session.id)


def test_approved_sessions_are_frozen():
    use_case, _ = make()
    session = start(use_case)
    answer_all(use_case, session.id)
    use_case.approve(session.id)
    with pytest.raises(InvalidOperationError):
        use_case.answer(session.id, "currency", "USD")
    with pytest.raises(InvalidOperationError):
        use_case.set_roles(session.id, {0: R.IGNORE})
    with pytest.raises(InvalidOperationError):
        use_case.choose_header(session.id, 1)
    assert use_case.preview(session.id).totals["accepted"] == 5


def test_role_problems_are_reported_when_the_builder_cannot_find_a_column():
    table = {**ROLES, "Codigo": (R.IGNORE, 0.9)}
    use_case, _ = make(stages=[ClassifierStage("heuristics", FakeClassifier(table))])
    session = start(use_case)
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED
    assert any("product code" in issue for issue in session.role_issues)
    assert session.questions == ()  # questions wait until the roles are consistent
    session = use_case.set_roles(session.id, {0: R.CODE})
    assert session.role_issues == ()
    assert session.status is SessionStatus.QUESTIONS_PENDING


def test_approve_refuses_a_session_without_accepted_rows():
    # Every data row lacks its product code, so the engine rejects all of them.
    rows = [HEADER, ("", "Tornillo", "1.210,00", "21%"), (None, "Tuerca", "968,00", "21%")]
    use_case, _ = make(rows=rows)
    session = start(use_case)
    answer_all(use_case, session.id)
    assert use_case.get(session.id).status is SessionStatus.READY_FOR_PREVIEW

    with pytest.raises(NoAcceptedRowsError):
        use_case.approve(session.id)

    assert use_case.get(session.id).status is SessionStatus.READY_FOR_PREVIEW
