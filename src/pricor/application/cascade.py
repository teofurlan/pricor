"""Classification cascade: heuristics, then a model, then the user.

Stages run in order (a stage that cannot run here is skipped with a notice). A column a stage classifies with a score at or above that
stage's threshold is settled and is not shown to later stages. An agreement stage runs two
classifiers and settles a column only when both choose the same role. Columns still
unsettled after the last stage get no role: the user decides.
"""

import logging
import time
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

logger = logging.getLogger(__name__)

# PLACEHOLDER: not calibrated on held-out data. It is calibrated in T21 (Q24);
# until then it only decides which columns are shown to the user for confirmation.
UNCALIBRATED_THRESHOLD = 0.75

QUANTITY_DISCOUNT_RATIONALE = (
    "quantity discount: its values depend on how much is bought, so no stage settles it as a discount"
)
RETAIL_PRICE_RATIONALE = "retail price is not used to compute unit cost"


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


def _suppress_retail_price(outcomes: dict[int, _Outcome]) -> dict[int, _Outcome]:
    """Never auto-suggest or settle `retail_price`; turn proposals into `ignore` for user confirmation."""
    result: dict[int, _Outcome] = {}
    for index, outcome in outcomes.items():
        proposals = tuple(
            StageProposal(
                item.stage,
                ColumnRole.IGNORE,
                item.score,
                f"{item.rationale} ({RETAIL_PRICE_RATIONALE})" if item.rationale else RETAIL_PRICE_RATIONALE,
            )
            if item.role is ColumnRole.RETAIL_PRICE
            else item
            for item in outcome.proposals
        )
        settled = (
            None
            if outcome.settled is not None and outcome.settled.role is ColumnRole.RETAIL_PRICE
            else outcome.settled
        )
        result[index] = _Outcome(proposals, settled)
    return result


_UNIQUE_ROLES = (ColumnRole.CODE, ColumnRole.DESCRIPTION, ColumnRole.COST_PRICE)


def _one_unique_role_suggestion(
    outcomes: dict[int, _Outcome],
    columns: dict[int, ColumnProfile],
    target_role: ColumnRole,
    role_settled: bool,
    contested: int | None,
) -> tuple[dict[int, _Outcome], int | None]:
    """Keep a unique required role's suggestion (`code`, `description`, `cost_price`) on one column.

    Several columns proposed for the same unique role cannot all be right: only the most complete
    one (fewest empty rows; a tie keeps the column order) keeps its suggestion, the rest lose
    theirs. While candidates compete, nothing is settled as that role: the user confirms which one
    it is. `contested` is the winner of a competition seen by an earlier stage: the contest stays
    open, so a later stage proposing a single column cannot settle it. Once an earlier stage
    settled that role, no later stage may propose it for another column.
    """
    candidates = [
        index
        for index, outcome in sorted(outcomes.items())
        if any(item.role is target_role for item in outcome.proposals)
    ]
    if contested is not None and contested in columns and contested not in candidates:
        candidates = sorted([*candidates, contested])
    if not candidates or (len(candidates) == 1 and not role_settled and contested is None):
        return outcomes, contested
    winner = None if role_settled else min(candidates, key=lambda index: (columns[index].empty_rows, index))
    result = dict(outcomes)
    for index in candidates:
        outcome = outcomes.get(index)
        if outcome is None:
            continue
        proposals = tuple(
            item for item in outcome.proposals if index == winner or item.role is not target_role
        )
        settled = outcome.settled
        if settled is not None and settled.role is target_role:
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
    contested: dict[ColumnRole, int | None] = {role: None for role in _UNIQUE_ROLES}

    for stage in stages:
        if not remaining:
            break
        if stage.skipped_reason is not None:
            notices.append(_skipped_notice(stage, stage.skipped_reason))
            continue
        subset = replace(profile, columns=tuple(remaining))
        evaluate = _agreement_outcomes if isinstance(stage, AgreementStage) else _classifier_outcomes
        started = time.perf_counter()
        try:
            outcomes = evaluate(stage, subset)
        except ModelNotInstalledError as error:
            logger.info("cascade stage %s: %.2fs", stage.name, time.perf_counter() - started)
            logger.warning("cascade stage %s skipped (%s): %s", stage.name, type(error).__name__, error)
            notices.append(_skipped_notice(stage, str(error)))
            continue
        except ModelError as error:
            logger.info("cascade stage %s: %.2fs", stage.name, time.perf_counter() - started)
            # The notice reaches the user; without this line a failed model call leaves no trace in the server logs.
            logger.warning("cascade stage %s failed (%s): %s", stage.name, type(error).__name__, error)
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
        logger.info("cascade stage %s: %.2fs", stage.name, time.perf_counter() - started)
        outcomes = _suppress_retail_price(outcomes)
        remaining_by_index = {column.index: column for column in remaining}
        for role in _UNIQUE_ROLES:
            role_settled = any(decision.role is role for decision in decisions.values())
            outcomes, contested[role] = _one_unique_role_suggestion(
                outcomes, remaining_by_index, role, role_settled, contested[role]
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
