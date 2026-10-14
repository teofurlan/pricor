"""Classification cascade: heuristics, then a model, then the user.

Stages run in order. A column a stage classifies with a score at or above that
stage's threshold is settled and is not shown to later stages. Columns still
unsettled after the last stage get no role: the user decides.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pricor.application.import_session import ColumnDecision, Notice, StageProposal
from pricor.domain.profile import SheetProfile
from pricor.ports.column_classifier import ColumnClassifier
from pricor.ports.model_errors import ModelError, ModelTimeoutError, ModelUnavailableError

# PLACEHOLDER: not calibrated on held-out data. It is calibrated in T21 (Q24);
# until then it only decides which columns are shown to the user for confirmation.
UNCALIBRATED_THRESHOLD = 0.75


@dataclass(frozen=True)
class ClassifierStage:
    name: str
    classifier: ColumnClassifier
    threshold: float = UNCALIBRATED_THRESHOLD
    threshold_calibrated: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be between 0 and 1, got {self.threshold}")


def run_cascade(
    stages: Sequence[ClassifierStage], profile: SheetProfile
) -> tuple[dict[int, ColumnDecision], list[Notice], bool]:
    """Classify every column of `profile`.

    Returns the decisions, any model notices, and whether a model server could
    not be reached (unavailable or timed out), so callers can avoid waiting on it again.
    """
    remaining = list(profile.columns)
    proposals: dict[int, list[StageProposal]] = {column.index: [] for column in remaining}
    decisions: dict[int, ColumnDecision] = {}
    notices: list[Notice] = []
    unreachable = False

    for stage in stages:
        if not remaining:
            break
        subset = replace(profile, columns=tuple(remaining))
        try:
            results = stage.classifier.classify_sheet(subset)
        except ModelError as error:
            notices.append(
                Notice(
                    "model_unavailable",
                    f"stage '{stage.name}' could not classify columns "
                    f"({type(error).__name__}): {error}",
                    stage.name,
                )
            )
            unreachable = isinstance(error, ModelUnavailableError | ModelTimeoutError)
            break
        by_index = {result.index: result for result in results}
        undecided = []
        for column in remaining:
            result = by_index.get(column.index)
            if result is None:
                undecided.append(column)
                continue
            proposal = StageProposal(stage.name, result.role, result.score, result.rationale)
            proposals[column.index].append(proposal)
            if result.score >= stage.threshold:
                decisions[column.index] = ColumnDecision(
                    column.index,
                    column.plan_header,
                    result.role,
                    stage.name,
                    result.score,
                    result.rationale,
                )
            else:
                undecided.append(column)
        remaining = undecided

    for column in remaining:
        seen = proposals[column.index]
        best = max(seen, key=lambda item: item.score, default=None)
        decisions[column.index] = ColumnDecision(
            column.index,
            column.plan_header,
            None,
            None,
            best.score if best else 0.0,
            best.rationale if best else "no stage produced a classification",
        )
    return {
        index: replace(decision, proposals=tuple(proposals[index]))
        for index, decision in decisions.items()
    }, notices, unreachable
