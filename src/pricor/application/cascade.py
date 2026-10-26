"""Classification cascade: heuristics, then a model, then the user.

Stages run in order (a stage that cannot run here is skipped with a notice). A column a stage classifies with a score at or above that
stage's threshold is settled and is not shown to later stages. An agreement stage runs two
classifiers and settles a column only when both choose the same role. Columns still
unsettled after the last stage get no role: the user decides.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pricor.domain.profile import ColumnProfile, SheetProfile
from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassifier
from pricor.ports.import_session import ColumnDecision, Notice, StageProposal
from pricor.ports.model_errors import (
    ModelError,
    ModelNotInstalledError,
    ModelTimeoutError,
    ModelUnavailableError,
)

# PLACEHOLDER: not calibrated on held-out data. It is calibrated in T21 (Q24);
# until then it only decides which columns are shown to the user for confirmation.
UNCALIBRATED_THRESHOLD = 0.75

QUANTITY_DISCOUNT_RATIONALE = (
    "quantity discount: its values depend on how much is bought, so no stage settles it as a discount"
)


@dataclass(frozen=True)
class ClassifierStage:
    name: str
    classifier: ColumnClassifier
    threshold: float = UNCALIBRATED_THRESHOLD
    threshold_calibrated: bool = False
    # Set when the stage cannot run in this installation (missing extra or weights). The cascade
    # skips it and tells the user why, instead of failing.
    skipped_reason: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be between 0 and 1, got {self.threshold}")


@dataclass(frozen=True)
class Member:
    """One classifier taking part in an agreement stage, with the name shown in rationales."""

    name: str
    classifier: ColumnClassifier


@dataclass(frozen=True)
class AgreementStage:
    """Settles a column when two classifiers choose the same role.

    `min_confidence` is an optional extra bar: at least one of the two must score the agreed
    role at or above it (the default 0 asks for agreement alone). Columns where they disagree,
    or agree too timidly, continue to the next stage.
    """

    name: str
    first: Member
    second: Member
    min_confidence: float = 0.0
    min_confidence_calibrated: bool = False
    skipped_reason: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be between 0 and 1, got {self.min_confidence}")


Stage = ClassifierStage | AgreementStage


@dataclass(frozen=True)
class _Outcome:
    """What a stage made of one column: what to show the user, and the answer if it settled it."""

    proposals: tuple[StageProposal, ...]
    settled: StageProposal | None = None


def _skipped_notice(stage: Stage, reason: str) -> Notice:
    return Notice("model_unavailable", f"stage '{stage.name}' was skipped: {reason}", stage.name)


def _classifier_outcomes(stage: ClassifierStage, subset: SheetProfile) -> dict[int, _Outcome]:
    outcomes = {}
    for result in stage.classifier.classify_sheet(subset):
        proposal = StageProposal(stage.name, result.role, result.score, result.rationale)
        settled = proposal if result.score >= stage.threshold else None
        outcomes[result.index] = _Outcome((proposal,), settled)
    return outcomes


def _agreement_outcomes(stage: AgreementStage, subset: SheetProfile) -> dict[int, _Outcome]:
    first = {r.index: r for r in stage.first.classifier.classify_sheet(subset)}
    second = {r.index: r for r in stage.second.classifier.classify_sheet(subset)}
    a, b = stage.first.name, stage.second.name
    outcomes = {}
    for index in first.keys() & second.keys():
        one, two = first[index], second[index]
        if one.role is not two.role:
            outcomes[index] = _Outcome(
                (
                    StageProposal(f"{stage.name}:{a}", one.role, one.score, one.rationale),
                    StageProposal(f"{stage.name}:{b}", two.role, two.score, two.rationale),
                )
            )
            continue
        score = max(one.score, two.score)
        rationale = (
            f"{stage.name}: {a} + {b} both chose {one.role.value}. "
            f"{a}: {one.rationale} | {b}: {two.rationale}"
        )
        if score >= stage.min_confidence:
            proposal = StageProposal(stage.name, one.role, score, rationale)
            outcomes[index] = _Outcome((proposal,), proposal)
        else:
            note = f" (below the minimum confidence {stage.min_confidence:g})"
            outcomes[index] = _Outcome((StageProposal(stage.name, one.role, score, rationale + note),))
    return outcomes


def _one_code_suggestion(
    outcomes: dict[int, _Outcome],
    columns: dict[int, ColumnProfile],
    code_settled: bool,
    contested: int | None,
) -> tuple[dict[int, _Outcome], int | None]:
    """Keep the `code` suggestion on a single column.

    Several columns proposed as the product code cannot all be right: only the most complete one
    (fewest empty rows; a tie keeps the column order) keeps its suggestion, the rest lose theirs.
    While candidates compete, nothing is settled as `code`: the user confirms which one it is.
    `contested` is the winner of a competition seen by an earlier stage: the contest stays open,
    so a later stage proposing a single column cannot settle it. Once an earlier stage settled
    `code`, no later stage may propose it for another column. Returns the open contest's winner.
    """
    candidates = [
        index
        for index, outcome in sorted(outcomes.items())
        if any(item.role is ColumnRole.CODE for item in outcome.proposals)
    ]
    if contested is not None and contested in columns and contested not in candidates:
        candidates = sorted([*candidates, contested])
    if not candidates or (len(candidates) == 1 and not code_settled and contested is None):
        return outcomes, contested
    winner = None if code_settled else min(candidates, key=lambda index: (columns[index].empty_rows, index))
    result = dict(outcomes)
    for index in candidates:
        outcome = outcomes.get(index)
        if outcome is None:
            continue
        proposals = tuple(
            item for item in outcome.proposals if index == winner or item.role is not ColumnRole.CODE
        )
        settled = outcome.settled
        if settled is not None and settled.role is ColumnRole.CODE:
            settled = None
        result[index] = _Outcome(proposals, settled)
    return result, winner


def run_cascade(
    stages: Sequence[Stage], profile: SheetProfile
) -> tuple[dict[int, ColumnDecision], list[Notice], bool]:
    """Classify every column of `profile`.

    Returns the decisions, any model notices, and whether a model server could
    not be reached (unavailable or timed out), so callers can avoid waiting on it again.
    """
    # A conditional quantity discount is never applicable to a unit cost: no stage may settle it
    # as a discount, so those columns skip the stages and wait for the user, with `ignore` suggested.
    held = [column for column in profile.columns if column.quantity_discount]
    remaining = [column for column in profile.columns if not column.quantity_discount]
    proposals: dict[int, list[StageProposal]] = {column.index: [] for column in profile.columns}
    for column in held:
        proposals[column.index].append(
            StageProposal("heuristics", ColumnRole.IGNORE, 0.9, QUANTITY_DISCOUNT_RATIONALE)
        )
    decisions: dict[int, ColumnDecision] = {}
    notices: list[Notice] = []
    unreachable = False
    contested_code: int | None = None

    for stage in stages:
        if not remaining:
            break
        if stage.skipped_reason is not None:
            notices.append(_skipped_notice(stage, stage.skipped_reason))
            continue
        subset = replace(profile, columns=tuple(remaining))
        evaluate = _agreement_outcomes if isinstance(stage, AgreementStage) else _classifier_outcomes
        try:
            outcomes = evaluate(stage, subset)
        except ModelNotInstalledError as error:
            notices.append(_skipped_notice(stage, str(error)))
            continue
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
        code_settled = any(decision.role is ColumnRole.CODE for decision in decisions.values())
        outcomes, contested_code = _one_code_suggestion(
            outcomes, {column.index: column for column in remaining}, code_settled, contested_code
        )
        undecided = []
        for column in remaining:
            outcome = outcomes.get(column.index)
            if outcome is None:
                undecided.append(column)
                continue
            proposals[column.index].extend(outcome.proposals)
            if outcome.settled is not None:
                answer = outcome.settled
                decisions[column.index] = ColumnDecision(
                    column.index,
                    column.plan_header,
                    answer.role,
                    stage.name,
                    answer.score,
                    answer.rationale,
                )
            else:
                undecided.append(column)
        remaining = undecided

    for column in [*remaining, *held]:
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
