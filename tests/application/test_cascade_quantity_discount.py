from pricor.application.cascade import AgreementStage, ClassifierStage, Member, run_cascade
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole

from .fakes import FakeClassifier

ROWS = [
    ["Codigo", "DTO_X_CANT"],
    ["A-1", " 10% x  10 UN"],
    ["A-2", "5% x 12 u."],
    ["A-3", "15% por 6 unidades"],
]
SURE = {"Codigo": (ColumnRole.CODE, 0.99), "DTO_X_CANT": (ColumnRole.DISCOUNT, 0.99)}


def test_a_quantity_discount_column_is_never_settled_by_a_classifier_stage():
    classifier = FakeClassifier(SURE)

    decisions, _, _ = run_cascade([ClassifierStage("heuristics", classifier, 0.5)], profile_sheet(ROWS))

    assert decisions[0].role is ColumnRole.CODE
    assert decisions[1].role is None and decisions[1].decided_by is None
    assert classifier.seen_indexes == [[0]]


def test_a_quantity_discount_column_is_never_settled_by_the_agreement_stage():
    stage = AgreementStage("agreement", Member("heuristics", FakeClassifier(SURE)), Member("laya", FakeClassifier(SURE)), 0.0, True)

    decisions, _, _ = run_cascade([stage], profile_sheet(ROWS))

    assert decisions[1].role is None


def test_the_column_is_suggested_as_ignore_for_the_user_to_confirm():
    decisions, _, _ = run_cascade([ClassifierStage("heuristics", FakeClassifier(SURE), 0.5)], profile_sheet(ROWS))

    suggestion = decisions[1].proposals[-1]
    assert (suggestion.role, suggestion.stage) == (ColumnRole.IGNORE, "heuristics")


CODE_ROWS = [
    ["CODIGO", "COD_PROV", "DESCRIP"],
    ["", "P-1", "Tornillo"],
    ["", "P-2", "Tuerca"],
    ["C-3", "P-3", "Arandela"],
    ["C-4", "P-4", "Clavo"],
]
TWO_CODES = {
    "CODIGO": (ColumnRole.CODE, 0.99),
    "COD_PROV": (ColumnRole.CODE, 0.99),
    "DESCRIP": (ColumnRole.DESCRIPTION, 0.99),
}


def _code_proposals(decision):
    return [item for item in decision.proposals if item.role is ColumnRole.CODE]


def test_only_the_most_complete_code_candidate_is_suggested_and_it_is_not_pre_settled():
    decisions, _, _ = run_cascade([ClassifierStage("heuristics", FakeClassifier(TWO_CODES), 0.5)], profile_sheet(CODE_ROWS))

    assert _code_proposals(decisions[0]) == []
    assert len(_code_proposals(decisions[1])) == 1
    assert decisions[0].role is None and decisions[1].role is None
    assert decisions[2].role is ColumnRole.DESCRIPTION


def test_a_tie_keeps_the_first_code_candidate():
    rows = [["CODIGO", "COD_PROV"], ["C-1", "P-1"], ["C-2", "P-2"]]
    decisions, _, _ = run_cascade([ClassifierStage("heuristics", FakeClassifier(TWO_CODES), 0.5)], profile_sheet(rows))

    assert len(_code_proposals(decisions[0])) == 1
    assert _code_proposals(decisions[1]) == []


def test_a_single_code_candidate_is_settled_as_before():
    rows = [["CODIGO", "DESCRIP"], ["C-1", "Tornillo"]]
    decisions, _, _ = run_cascade([ClassifierStage("heuristics", FakeClassifier(TWO_CODES), 0.5)], profile_sheet(rows))

    assert decisions[0].role is ColumnRole.CODE and decisions[0].decided_by == "heuristics"


def test_the_agreement_stage_does_not_settle_two_competing_code_columns():
    stage = AgreementStage("agreement", Member("heuristics", FakeClassifier(TWO_CODES)), Member("laya", FakeClassifier(TWO_CODES)), 0.0, True)

    decisions, _, _ = run_cascade([stage], profile_sheet(CODE_ROWS))

    assert decisions[0].role is None and decisions[1].role is None
    assert _code_proposals(decisions[0]) == [] and len(_code_proposals(decisions[1])) == 1


def test_a_later_stage_does_not_propose_code_once_a_column_settled_it():
    first = ClassifierStage("heuristics", FakeClassifier({"CODIGO": (ColumnRole.CODE, 0.99)}), 0.5)
    second = ClassifierStage("model", FakeClassifier({"COD_PROV": (ColumnRole.CODE, 0.99)}), 0.5)

    decisions, _, _ = run_cascade([first, second], profile_sheet(CODE_ROWS))

    assert decisions[0].role is ColumnRole.CODE
    assert _code_proposals(decisions[1]) == []


def test_a_later_stage_cannot_settle_code_while_an_earlier_stage_saw_two_candidates():
    first = ClassifierStage("heuristics", FakeClassifier(TWO_CODES), 0.5)
    second = ClassifierStage("model", FakeClassifier({"CODIGO": (ColumnRole.CODE, 0.99)}), 0.5)

    decisions, _, _ = run_cascade([first, second], profile_sheet(CODE_ROWS))

    assert decisions[0].role is None and decisions[1].role is None
    assert _code_proposals(decisions[0]) == []
    assert len(_code_proposals(decisions[1])) == 1


def _proposals_for(decision, role):
    return [item for item in decision.proposals if item.role is role]


def test_only_the_most_complete_cost_price_candidate_is_suggested_and_not_pre_settled():
    rows = [
        ["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"],
        ["001", "Detergente", "1286.26", "64.31"],
        ["002", "Cera", "2635.08", ""],
        ["003", "Escoba", "250.80", ""],
    ]
    two_costs = {
        "COD_ALFA": (ColumnRole.CODE, 0.99),
        "DETALLE": (ColumnRole.DESCRIPTION, 0.99),
        "PRECIO": (ColumnRole.COST_PRICE, 0.99),
        "PR. UNIT": (ColumnRole.COST_PRICE, 0.99),
    }

    decisions, _, _ = run_cascade(
        [ClassifierStage("heuristics", FakeClassifier(two_costs), 0.5)],
        profile_sheet(rows),
    )

    assert decisions[0].role is ColumnRole.CODE
    assert decisions[1].role is ColumnRole.DESCRIPTION
    # PRECIO (0 empty rows) keeps cost_price suggestion; PR. UNIT (2 empty rows) loses it; neither is pre-settled.
    assert decisions[2].role is None and len(_proposals_for(decisions[2], ColumnRole.COST_PRICE)) == 1
    assert decisions[3].role is None and _proposals_for(decisions[3], ColumnRole.COST_PRICE) == []


def test_competing_description_candidates_keep_only_most_complete_and_require_confirmation():
    rows = [
        ["COD", "DESC_1", "DESC_2", "PRECIO"],
        ["001", "", "Tornillo", "100"],
        ["002", "Tuerca", "Tuerca M8", "200"],
    ]
    two_descs = {
        "COD": (ColumnRole.CODE, 0.99),
        "DESC_1": (ColumnRole.DESCRIPTION, 0.99),
        "DESC_2": (ColumnRole.DESCRIPTION, 0.99),
        "PRECIO": (ColumnRole.COST_PRICE, 0.99),
    }

    decisions, _, _ = run_cascade(
        [ClassifierStage("heuristics", FakeClassifier(two_descs), 0.5)],
        profile_sheet(rows),
    )

    assert decisions[1].role is None and _proposals_for(decisions[1], ColumnRole.DESCRIPTION) == []
    assert decisions[2].role is None and len(_proposals_for(decisions[2], ColumnRole.DESCRIPTION)) == 1
    assert decisions[3].role is ColumnRole.COST_PRICE
