import pytest

from pricor.application.cascade import AgreementStage, ClassifierStage, Member, run_cascade
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.model_errors import ModelNotInstalledError, ModelUnavailableError

from .fakes import FakeClassifier

ROWS = [["Codigo", "Precio", "Detalle"], ["A-1", "10", "Tornillo"], ["A-2", "20", "Tuerca"]]


def agreement(first, second, min_confidence=0.0, skipped_reason=None):
    return AgreementStage(
        "agreement", Member("heuristics", first), Member("laya", second), min_confidence, True, skipped_reason
    )


def test_a_confidence_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError, match="min_confidence"):
        agreement(FakeClassifier(), FakeClassifier(), min_confidence=1.2)


def test_a_column_both_classifiers_label_the_same_role_is_settled_by_the_agreement_stage():
    table = {"Codigo": (ColumnRole.CODE, 0.6), "Precio": (ColumnRole.COST_PRICE, 0.7)}
    stage = agreement(FakeClassifier(table), FakeClassifier({**table, "Precio": (ColumnRole.COST_PRICE, 0.9)}))

    decisions, notices, _ = run_cascade([stage], profile_sheet(ROWS))

    assert decisions[0].role is ColumnRole.CODE and decisions[0].decided_by == "agreement"
    assert decisions[1].role is ColumnRole.COST_PRICE and decisions[1].score == 0.9  # the higher of the two
    assert notices == []


def test_the_decision_names_both_classifiers_and_keeps_both_rationales():
    table = {"Codigo": (ColumnRole.CODE, 0.6)}
    stage = agreement(FakeClassifier(table), FakeClassifier(table))

    decisions, _, _ = run_cascade([stage], profile_sheet(ROWS))

    rationale = decisions[0].rationale
    assert rationale.startswith("agreement: heuristics + laya both chose code")
    assert "heuristics: fake:Codigo" in rationale and "laya: fake:Codigo" in rationale
    assert [(p.stage, p.role) for p in decisions[0].proposals] == [("agreement", ColumnRole.CODE)]


def test_columns_where_the_two_classifiers_disagree_pass_on_to_the_next_stage():
    first = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.99)})
    second = FakeClassifier({"Codigo": (ColumnRole.DESCRIPTION, 0.99)})
    after = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.9)})

    decisions, _, _ = run_cascade(
        [agreement(first, second), ClassifierStage("gemma", after, 0.5)], profile_sheet(ROWS)
    )

    assert decisions[0].decided_by == "gemma"
    assert after.seen_indexes == [[0]]  # the other two columns agreed (both ignore) and were settled
    stages = [(p.stage, p.role) for p in decisions[0].proposals]
    assert stages == [
        ("agreement:heuristics", ColumnRole.CODE),
        ("agreement:laya", ColumnRole.DESCRIPTION),
        ("gemma", ColumnRole.CODE),
    ]


def test_agreement_below_the_minimum_confidence_passes_on_and_says_so():
    table = {"Codigo": (ColumnRole.CODE, 0.8)}
    after = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.9)})

    decisions, _, _ = run_cascade(
        [agreement(FakeClassifier(table), FakeClassifier(table), min_confidence=0.95), ClassifierStage("gemma", after, 0.5)],
        profile_sheet(ROWS),
    )

    assert decisions[0].decided_by == "gemma"
    first = decisions[0].proposals[0]
    assert first.stage == "agreement" and first.role is ColumnRole.CODE
    assert "below the minimum confidence 0.95" in first.rationale


def test_one_confident_classifier_is_enough_to_reach_the_minimum_confidence():
    first = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.3)})
    second = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.97)})

    decisions, _, _ = run_cascade([agreement(first, second, min_confidence=0.95)], profile_sheet(ROWS))

    assert decisions[0].decided_by == "agreement"


def test_the_next_stage_only_sees_the_columns_the_agreement_stage_left():
    table = {"Codigo": (ColumnRole.CODE, 0.9)}
    differs = {**table, "Precio": (ColumnRole.COST_PRICE, 0.9), "Detalle": (ColumnRole.DESCRIPTION, 0.9)}
    after = FakeClassifier()

    run_cascade(
        [agreement(FakeClassifier(table), FakeClassifier(differs)), ClassifierStage("gemma", after, 0.5)],
        profile_sheet(ROWS),
    )

    assert after.seen_indexes == [[1, 2]]


def test_a_stage_marked_skipped_never_runs_and_leaves_a_notice():
    first, second = FakeClassifier(), FakeClassifier()

    decisions, notices, _ = run_cascade(
        [agreement(first, second, skipped_reason="the 'laya' extra is not installed")], profile_sheet(ROWS)
    )

    assert first.seen_indexes == second.seen_indexes == []
    assert [(n.code, n.stage) for n in notices] == [("model_unavailable", "agreement")]
    assert "extra is not installed" in notices[0].message
    assert all(d.role is None for d in decisions.values())


def test_a_member_whose_model_is_not_installed_skips_the_stage_and_the_cascade_goes_on():
    missing = FakeClassifier(error=ModelNotInstalledError("laya missing"))
    after = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.9)})

    decisions, notices, unreachable = run_cascade(
        [agreement(FakeClassifier(), missing), ClassifierStage("gemma", after, 0.5)], profile_sheet(ROWS)
    )

    assert decisions[0].decided_by == "gemma"
    assert [(n.code, n.stage) for n in notices] == [("model_unavailable", "agreement")]
    assert unreachable is False


def test_an_unreachable_member_ends_the_cascade_like_any_other_stage():
    down = FakeClassifier(error=ModelUnavailableError("server down"))
    after = FakeClassifier()

    _, notices, unreachable = run_cascade(
        [agreement(FakeClassifier(), down), ClassifierStage("gemma", after, 0.5)], profile_sheet(ROWS)
    )

    assert unreachable is True and after.seen_indexes == []
    assert len(notices) == 1
