import pytest

from tools.benchmark.metrics import (
    Answer,
    calibrate_threshold,
    label_metrics,
    latency_summary,
    simulate_cascade,
    summarize_cascade,
)


# -- calibration --


def samples(*pairs):
    return [(score, correct) for score, correct in pairs]


def test_the_lowest_threshold_whose_accepted_answers_meet_the_target_is_chosen():
    data = samples((0.2, False), (0.4, False), (0.6, True), (0.7, True), (0.8, True), (0.9, True))

    result = calibrate_threshold(data, target_precision=1.0, min_support=3)

    assert result.threshold == 0.6
    assert (result.support, result.precision) == (4, 1.0)
    assert result.total == 6


def test_a_target_below_one_tolerates_the_stated_share_of_errors():
    data = samples((0.5, False), (0.6, True), (0.7, True), (0.8, True), (0.9, True))

    result = calibrate_threshold(data, target_precision=0.8, min_support=2)

    assert result.threshold == 0.5
    assert result.precision == pytest.approx(0.8)


def test_a_threshold_that_leaves_too_few_answers_is_not_accepted():
    data = samples((0.5, False), (0.6, False), (0.9, True), (0.95, True))

    result = calibrate_threshold(data, target_precision=1.0, min_support=3)

    assert result.threshold is None
    assert "support" in result.reason


def test_no_threshold_is_reported_when_the_target_cannot_be_met():
    data = samples((0.9, False), (0.95, False), (0.99, True))

    result = calibrate_threshold(data, target_precision=1.0, min_support=1)

    assert result.threshold == 0.99
    worse = calibrate_threshold(samples((0.9, False), (0.95, False)), 1.0, 1)
    assert worse.threshold is None


def test_a_calibration_on_no_data_has_no_threshold():
    assert calibrate_threshold([], 0.95, 5).threshold is None


# -- per-label metrics --


def test_precision_and_recall_are_computed_per_label_and_undefined_when_there_is_no_basis():
    pairs = [("code", "code"), ("code", "ignore"), ("ignore", "ignore"), ("ignore", "ignore")]

    metrics = label_metrics(pairs)

    assert metrics["code"] == {"support": 2, "predicted": 1, "correct": 1, "precision": 1.0, "recall": 0.5}
    assert metrics["ignore"]["precision"] == pytest.approx(2 / 3)
    assert metrics["cost_price"] == {
        "support": 0,
        "predicted": 0,
        "correct": 0,
        "precision": None,
        "recall": None,
    }


# -- cascade simulation --


def answers(**by_stage):
    return by_stage


def test_a_column_is_settled_by_the_first_stage_that_reaches_its_threshold():
    outputs = {
        "laya": [Answer("code", 0.95), Answer("cost_price", 0.40), Answer("ignore", 0.10)],
        "gemma": [Answer("code", 0.9), Answer("cost_price", 0.80), Answer("description", 0.30)],
    }

    outcomes = simulate_cascade(
        ["code", "cost_price", "description"], outputs, ["laya", "gemma"], {"laya": 0.9, "gemma": 0.5}
    )

    assert [(o.resolved_by, o.predicted) for o in outcomes] == [
        ("laya", "code"),
        ("gemma", "cost_price"),
        (None, None),
    ]
    assert outcomes[2].best_guess == "description"
    assert outcomes[2].expected == "description"


def test_the_summary_counts_coverage_and_the_accuracy_of_what_was_resolved_automatically():
    outputs = {
        "laya": [Answer("code", 0.95), Answer("ignore", 0.95), Answer("ignore", 0.1), Answer("ignore", 0.1)],
        "gemma": [Answer("code", 0.9)] * 4,
    }
    outcomes = simulate_cascade(
        ["code", "code", "code", "ignore"], outputs, ["laya", "gemma"], {"laya": 0.9, "gemma": 0.5}
    )

    summary = summarize_cascade(outcomes, ["laya", "gemma"])

    assert summary["total"] == 4
    assert summary["resolved_by"] == {"laya": 2, "gemma": 2, "user": 0}
    assert summary["auto_resolved"] == 4
    assert summary["auto_correct"] == 2
    assert summary["auto_accuracy"] == 0.5
    assert summary["escalation_rate"] == 0.0


def test_the_summary_handles_an_empty_run():
    summary = summarize_cascade([], ["laya"])

    assert summary["total"] == 0
    assert summary["auto_accuracy"] is None


# -- latency --


def test_latency_is_summarized_in_milliseconds():
    summary = latency_summary([0.010, 0.020, 0.030, 0.100])

    assert summary["n"] == 4
    assert summary["mean_ms"] == pytest.approx(40.0)
    assert summary["median_ms"] == pytest.approx(25.0)
    assert summary["max_ms"] == pytest.approx(100.0)


def test_no_latency_samples_give_an_empty_summary():
    assert latency_summary([]) == {"n": 0, "mean_ms": None, "median_ms": None, "p95_ms": None, "max_ms": None}
