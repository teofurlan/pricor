from pricor.application.cascade import AgreementStage, ClassifierStage, Member, run_cascade
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole

from .fakes import FakeClassifier

ROWS = [
    ["Codigo", "Descripcion", "Costo", "PVP"],
    ["A-1", "Tornillo 8x1", "100,00", "150,00"],
    ["A-2", "Tuerca M8", "50,00", "75,00"],
]

WITH_RETAIL = {
    "Codigo": (ColumnRole.CODE, 0.99),
    "Descripcion": (ColumnRole.DESCRIPTION, 0.99),
    "Costo": (ColumnRole.COST_PRICE, 0.99),
    "PVP": (ColumnRole.RETAIL_PRICE, 0.99),
}


def test_retail_price_column_is_never_settled_or_suggested_by_a_classifier_stage():
    classifier = FakeClassifier(WITH_RETAIL)

    decisions, _, _ = run_cascade(
        [ClassifierStage("heuristics", classifier, 0.5)], profile_sheet(ROWS)
    )

    assert decisions[0].role is ColumnRole.CODE
    assert decisions[1].role is ColumnRole.DESCRIPTION
    assert decisions[2].role is ColumnRole.COST_PRICE
    assert decisions[3].role is None
    assert decisions[3].decided_by is None
    assert [p.role for p in decisions[3].proposals] == [ColumnRole.IGNORE]


def test_retail_price_column_is_never_settled_or_suggested_by_agreement_stage():
    stage = AgreementStage(
        "agreement",
        Member("heuristics", FakeClassifier(WITH_RETAIL)),
        Member("laya", FakeClassifier(WITH_RETAIL)),
        0.0,
        True,
    )

    decisions, _, _ = run_cascade([stage], profile_sheet(ROWS))

    assert decisions[3].role is None
    assert decisions[3].decided_by is None
    assert [p.role for p in decisions[3].proposals] == [ColumnRole.IGNORE]


def test_retail_price_never_surfaces_across_multiple_stages():
    low = ClassifierStage("heuristics", FakeClassifier({"PVP": (ColumnRole.RETAIL_PRICE, 0.4)}), 0.75)
    high = ClassifierStage("gemma", FakeClassifier({"PVP": (ColumnRole.RETAIL_PRICE, 0.95)}), 0.75)

    decisions, _, _ = run_cascade([low, high], profile_sheet(ROWS))

    assert decisions[3].role is None
    assert all(p.role is ColumnRole.IGNORE for p in decisions[3].proposals)
    assert len(decisions[3].proposals) == 2
