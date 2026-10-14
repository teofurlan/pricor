from pricor.application.cascade import ClassifierStage
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole
from tests.application.fakes import FakeClassifier
from tools.benchmark.cascade_eval import choose_order, run_real_cascade, variant_summaries
from tools.benchmark.datasets import SheetCase
from tools.benchmark.metrics import Answer

ROWS = (("Codigo", "Detalle", "Costo"), ("A1", "Tornillo", "10,5"), ("A2", "Tuerca", "20,0"))


def case():
    return SheetCase("acme-1", "S", profile_sheet(ROWS), {0: "code", 1: "description", 2: "cost_price"})


def test_the_real_cascade_runs_on_whole_sheets_and_attributes_each_column_to_its_stage():
    first = FakeClassifier({"Codigo": (ColumnRole.CODE, 0.99)})
    second = FakeClassifier({"Detalle": (ColumnRole.DESCRIPTION, 0.9), "Costo": (ColumnRole.IGNORE, 0.9)})
    stages = [ClassifierStage("laya", first, 0.9), ClassifierStage("gemma", second, 0.5)]

    outcomes = run_real_cascade([case()], stages)

    assert [(o.expected, o.resolved_by, o.predicted) for o in outcomes] == [
        ("code", "laya", "code"),
        ("description", "gemma", "description"),
        ("cost_price", "gemma", "ignore"),
    ]
    assert second.seen_indexes == [[1, 2]]  # the second stage only sees what the first left over


def test_escalated_columns_keep_the_best_guess_of_the_stages_that_looked_at_them():
    stages = [ClassifierStage("laya", FakeClassifier({"Costo": (ColumnRole.COST_PRICE, 0.6)}), 0.9)]

    outcomes = run_real_cascade([case()], stages)

    escalated = [o for o in outcomes if o.resolved_by is None]
    assert len(escalated) == 3
    assert [o.best_guess for o in escalated if o.expected == "cost_price"] == ["cost_price"]


def answers_for(roles_scores):
    return [Answer(role, score) for role, score in roles_scores]


def test_every_stage_order_is_summarized_on_the_same_answers():
    expected = ["code", "code"]
    outputs = {
        "heuristics": answers_for([("code", 0.9), ("ignore", 0.9)]),
        "laya": answers_for([("code", 0.95), ("code", 0.95)]),
        "gemma": answers_for([("code", 0.9), ("code", 0.9)]),
    }

    summaries = variant_summaries(expected, outputs, {"heuristics": 0.8, "laya": 0.9, "gemma": 0.5})

    assert summaries["laya>gemma"]["auto_accuracy"] == 1.0
    assert summaries["heuristics>laya>gemma"]["auto_accuracy"] == 0.5
    assert summaries["laya"]["resolved_by"] == {"laya": 2, "user": 0}


def test_the_order_with_the_least_escalation_that_meets_the_target_wins_ties_go_to_the_default():
    summaries = {
        "laya>gemma": {"auto_accuracy": 0.96, "escalation_rate": 0.1},
        "heuristics>laya>gemma": {"auto_accuracy": 0.96, "escalation_rate": 0.1},
        "laya": {"auto_accuracy": 0.97, "escalation_rate": 0.3},
        "gemma": {"auto_accuracy": 0.90, "escalation_rate": 0.0},
    }

    assert choose_order(summaries, target_precision=0.95, default="laya>gemma") == "laya>gemma"
    summaries["heuristics>laya>gemma"]["escalation_rate"] = 0.05
    assert choose_order(summaries, target_precision=0.95, default="laya>gemma") == "heuristics>laya>gemma"


def test_when_no_order_meets_the_target_the_default_is_kept():
    summaries = {"laya>gemma": {"auto_accuracy": 0.8, "escalation_rate": 0.1}}

    assert choose_order(summaries, 0.95, "laya>gemma") == "laya>gemma"
