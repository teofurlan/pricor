from pricor.application.cascade import ClassifierStage, run_cascade
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.model_errors import ModelNotInstalledError, ModelUnavailableError

from .fakes import FakeClassifier

ROWS = [["Codigo", "Precio"], ["A-1", "10"], ["A-2", "20"]]
CONFIDENT = {"Codigo": (ColumnRole.CODE, 0.99), "Precio": (ColumnRole.COST_PRICE, 0.99)}


def test_a_stage_marked_skipped_never_runs_and_leaves_a_visible_notice():
    skipped, next_stage = FakeClassifier(CONFIDENT), FakeClassifier(CONFIDENT)
    stages = [
        ClassifierStage("laya", skipped, skipped_reason="the 'laya' extra is not installed"),
        ClassifierStage("heuristics", next_stage),
    ]

    decisions, notices, unreachable = run_cascade(stages, profile_sheet(ROWS))

    assert skipped.seen_indexes == []
    assert {d.decided_by for d in decisions.values()} == {"heuristics"}
    assert [(n.code, n.stage) for n in notices] == [("model_unavailable", "laya")]
    assert "extra is not installed" in notices[0].message
    assert unreachable is False


def test_a_stage_whose_model_is_not_installed_is_skipped_and_the_next_stage_still_runs():
    missing = FakeClassifier(error=ModelNotInstalledError("laya missing"))
    after = FakeClassifier(CONFIDENT)

    decisions, notices, unreachable = run_cascade(
        [ClassifierStage("laya", missing), ClassifierStage("gemma", after)], profile_sheet(ROWS)
    )

    assert {d.decided_by for d in decisions.values()} == {"gemma"}
    assert [(n.code, n.stage) for n in notices] == [("model_unavailable", "laya")]
    assert unreachable is False


def test_an_unreachable_server_still_ends_the_cascade():
    down = FakeClassifier(error=ModelUnavailableError("ollama is down"))
    after = FakeClassifier(CONFIDENT)

    _, notices, unreachable = run_cascade(
        [ClassifierStage("gemma", down), ClassifierStage("later", after)], profile_sheet(ROWS)
    )

    assert after.seen_indexes == []
    assert unreachable is True
    assert len(notices) == 1
