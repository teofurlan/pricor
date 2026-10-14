"""Pure scoring, calibration and cascade simulation for the benchmark. No models, no files."""

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pricor.domain.roles import ColumnRole

ROLE_NAMES = tuple(role.value for role in ColumnRole)


@dataclass(frozen=True)
class Answer:
    """What one classifier said about one column."""

    role: str
    score: float


# -- calibration ------------------------------------------------------------------


@dataclass(frozen=True)
class Calibration:
    """The outcome of choosing a stage's confidence threshold on a validation set."""

    threshold: float | None  # None: no threshold met the target with enough support
    target_precision: float
    min_support: int
    precision: float | None  # of the answers accepted at `threshold`
    support: int  # how many answers `threshold` accepts
    total: int  # how many validation answers there were
    reason: str


def calibrate_threshold(
    samples: Sequence[tuple[float, bool]], target_precision: float, min_support: int
) -> Calibration:
    """The lowest confidence whose accepted answers (score >= threshold) are precise enough.

    `samples` pairs each answer's confidence with whether the answer was right. Candidate
    thresholds are the observed scores, scanned from the lowest; the first one that accepts at
    least `min_support` answers with precision >= `target_precision` wins. Precision is not
    monotonic in the threshold, so taking the lowest one is the choice that escalates the least.
    """
    total = len(samples)
    for threshold in sorted({score for score, _ in samples}):
        accepted = [correct for score, correct in samples if score >= threshold]
        if len(accepted) < min_support:
            break  # higher thresholds only accept fewer
        precision = sum(accepted) / len(accepted)
        if precision >= target_precision:
            return Calibration(
                threshold, target_precision, min_support, precision, len(accepted), total, "met"
            )
    reason = (
        "no threshold meets the target precision with the minimum support"
        if total >= min_support
        else f"too little support: {total} answers, {min_support} needed"
    )
    return Calibration(None, target_precision, min_support, None, 0, total, reason)


# -- label metrics ----------------------------------------------------------------


def label_metrics(pairs: Sequence[tuple[str, str]]) -> dict[str, dict]:
    """Per label support, predicted, correct, precision and recall of (expected, predicted) pairs.

    Precision is None when the label was never predicted and recall is None when it never occurs.
    """
    table = {name: {"support": 0, "predicted": 0, "correct": 0} for name in ROLE_NAMES}
    for expected, predicted in pairs:
        table[expected]["support"] += 1
        table[predicted]["predicted"] += 1
        if expected == predicted:
            table[expected]["correct"] += 1
    return {
        name: {
            **row,
            "precision": row["correct"] / row["predicted"] if row["predicted"] else None,
            "recall": row["correct"] / row["support"] if row["support"] else None,
        }
        for name, row in table.items()
    }


# -- cascade simulation -----------------------------------------------------------


@dataclass(frozen=True)
class CascadeOutcome:
    expected: str
    resolved_by: str | None  # a stage name, or None when the user has to decide
    predicted: str | None  # the settled role (None when escalated)
    best_guess: str | None  # the highest-scoring proposal, for escalated columns


def simulate_cascade(
    expected: Sequence[str],
    outputs: Mapping[str, Sequence[Answer]],
    order: Sequence[str],
    thresholds: Mapping[str, float],
) -> list[CascadeOutcome]:
    """Replay a cascade from the per-column answers every stage gave.

    A column is settled by the first stage in `order` whose score reaches that stage's
    threshold; otherwise it goes to the user and `best_guess` is the best-scoring answer seen.
    """
    outcomes = []
    for position, truth in enumerate(expected):
        seen: list[Answer] = []
        settled: tuple[str, str] | None = None
        for stage in order:
            answer = outputs[stage][position]
            seen.append(answer)
            if answer.score >= thresholds[stage]:
                settled = (stage, answer.role)
                break
        if settled:
            outcomes.append(CascadeOutcome(truth, settled[0], settled[1], None))
        else:
            best = max(seen, key=lambda item: item.score).role if seen else None
            outcomes.append(CascadeOutcome(truth, None, None, best))
    return outcomes


def summarize_cascade(outcomes: Sequence[CascadeOutcome], order: Sequence[str]) -> dict:
    """Coverage and accuracy: who settled how many columns, and how right the automatic ones are."""
    total = len(outcomes)
    resolved_by = {stage: sum(o.resolved_by == stage for o in outcomes) for stage in order}
    resolved_by["user"] = sum(o.resolved_by is None for o in outcomes)
    auto = [o for o in outcomes if o.resolved_by is not None]
    auto_correct = sum(o.predicted == o.expected for o in auto)
    escalated = [o for o in outcomes if o.resolved_by is None]
    return {
        "total": total,
        "resolved_by": resolved_by,
        "auto_resolved": len(auto),
        "auto_correct": auto_correct,
        "auto_accuracy": auto_correct / len(auto) if auto else None,
        "escalation_rate": len(escalated) / total if total else None,
        "escalated_best_guess_correct": sum(o.best_guess == o.expected for o in escalated),
    }


# -- latency ----------------------------------------------------------------------


def latency_summary(seconds: Sequence[float]) -> dict:
    """Mean, median, 95th percentile and max, in milliseconds."""
    if not seconds:
        return {"n": 0, "mean_ms": None, "median_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(seconds)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "n": len(ordered),
        "mean_ms": statistics.mean(ordered) * 1000,
        "median_ms": statistics.median(ordered) * 1000,
        "p95_ms": p95 * 1000,
        "max_ms": ordered[-1] * 1000,
    }
