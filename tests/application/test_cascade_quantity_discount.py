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
