"""Evaluate the cascade: replay stage orders from cached answers, and run the real one."""

from collections.abc import Mapping, Sequence

from pricor.application.cascade import ClassifierStage, run_cascade

from .datasets import SheetCase
from .metrics import Answer, CascadeOutcome, simulate_cascade, summarize_cascade

DEFAULT_ORDER = "laya>gemma"
# Every order worth comparing; "heuristics" is the keyword stage, "laya" the fine-tuned model.
ORDERS = (
    "laya>gemma",
    "heuristics>laya>gemma",
    "laya>heuristics>gemma",
    "heuristics>gemma",
    "laya",
    "heuristics",
    "gemma",
)


def variant_summaries(
    expected: Sequence[str],
    outputs: Mapping[str, Sequence[Answer]],
    thresholds: Mapping[str, float],
    orders: Sequence[str] = ORDERS,
) -> dict[str, dict]:
    """Coverage and accuracy of every stage order, replayed from the same per-column answers."""
    summaries = {}
    for label in orders:
        order = label.split(">")
        if not all(stage in outputs for stage in order):
            continue
        outcomes = simulate_cascade(expected, outputs, order, thresholds)
        summaries[label] = summarize_cascade(outcomes, order)
    return summaries


def choose_order(summaries: Mapping[str, Mapping], target_precision: float, default: str = DEFAULT_ORDER) -> str:
    """The order that escalates least while its automatic answers meet the precision target.

    Decided on validation summaries only. Ties, and the case where nothing meets the target,
    keep the default order.
    """
    meeting = {
        label: summary
        for label, summary in summaries.items()
        if summary["auto_accuracy"] is not None and summary["auto_accuracy"] >= target_precision
    }
    if not meeting:
        return default
    best = min(summary["escalation_rate"] for summary in meeting.values())
    leaders = [label for label, summary in meeting.items() if summary["escalation_rate"] == best]
    return default if default in leaders else sorted(leaders)[0]


def run_real_cascade(cases: Sequence[SheetCase], stages: Sequence[ClassifierStage]) -> list[CascadeOutcome]:
    """Run the application's own cascade over whole sheets and score the labeled columns."""
    outcomes = []
    for case in cases:
        decisions, _, _ = run_cascade(stages, case.profile)
        columns = {column.index: column for column in case.profile.columns}
        for index, expected in case.expected_in_order():
            decision = decisions[columns[index].index]
            if decision.role is not None:
                outcomes.append(CascadeOutcome(expected, decision.decided_by, decision.role.value, None))
            else:
                best = max(decision.proposals, key=lambda item: item.score, default=None)
                outcomes.append(
                    CascadeOutcome(expected, None, None, best.role.value if best else None)
                )
    return outcomes
