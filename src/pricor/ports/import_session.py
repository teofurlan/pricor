"""State of one import session and the views the use cases return."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pricor.ports.question_model import Question
from pricor.domain.engine import ImportResult
from pricor.domain.fx import FxSnapshot
from pricor.domain.plan import ConvertCurrency, ImportPlan
from pricor.domain.profile import SheetProfile
from pricor.domain.roles import ColumnRole
from pricor.ports.plan_advisor import ParameterId, PlanProposal


class SessionStatus(StrEnum):
    HEADER_CHOICE_REQUIRED = "header_choice_required"
    ROLE_CONFIRMATION_REQUIRED = "role_confirmation_required"
    QUESTIONS_PENDING = "questions_pending"
    FX_RATE_REQUIRED = "fx_rate_required"
    READY_FOR_PREVIEW = "ready_for_preview"
    APPROVED = "approved"


@dataclass(frozen=True)
class HeaderCandidate:
    row_index: int  # 0-based position in the sheet
    file_row: int  # 1-based row number as the user sees it in the file
    cells: tuple[str, ...]


@dataclass(frozen=True)
class StageProposal:
    """What one cascade stage said about one column."""

    stage: str
    role: ColumnRole
    score: float
    rationale: str


@dataclass(frozen=True)
class ColumnDecision:
    """The role of one column and who settled it.

    `role` is `None` while the column still needs the user; `proposals` keeps
    what every stage that looked at it said, in cascade order.
    """

    index: int
    header: str
    role: ColumnRole | None
    decided_by: str | None  # a stage name, "user", or None while undecided
    score: float
    rationale: str
    proposals: tuple[StageProposal, ...] = ()


@dataclass(frozen=True)
class Notice:
    code: str
    message: str
    stage: str | None = None


@dataclass(frozen=True)
class PlanChange:
    """One difference between the new file and the saved plan it reuses.

    `kind` is one of `moved`, `retyped`, `new`, `missing`, `sheet_changed` or
    `header_row_changed`. `header` is the normalized column header; `role` is what the saved
    plan used the column for (only known for columns it read); `used_by_plan` flags a missing
    column the plan depended on. Sheet changes carry `old_value`/`new_value`, header-row
    changes carry 0-based `old_index`/`new_index`.
    """

    kind: str
    header: str = ""
    old_index: int | None = None
    new_index: int | None = None
    old_type: str | None = None
    new_type: str | None = None
    used_by_plan: bool = False
    role: str | None = None
    old_value: str | None = None
    new_value: str | None = None


@dataclass(frozen=True)
class PreviewTraceStep:
    step: str
    value: str


@dataclass(frozen=True)
class PreviewRow:
    row_number: int  # 1-based file row
    status: str  # "accepted" | "rejected"
    original: tuple[str, ...]
    trace: tuple[PreviewTraceStep, ...]
    record: dict[str, str | None] | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PreviewPage:
    offset: int
    limit: int
    total_items: int
    items: tuple[PreviewRow, ...]
    totals: dict[str, Any]


@dataclass
class ImportSession:
    id: str
    supplier_name: str
    file_name: str
    sheet_name: str
    language: str
    rows: tuple[Sequence[Any], ...]
    profile: SheetProfile
    header_confirmed: bool
    header_candidates: tuple[HeaderCandidate, ...] = ()
    decisions: dict[int, ColumnDecision] = field(default_factory=dict)
    answers: dict[ParameterId, str] = field(default_factory=dict)
    questions: tuple[Question, ...] = ()
    role_issues: tuple[str, ...] = ()
    plan: ImportPlan | None = None
    result: ImportResult | None = None
    notices: list[Notice] = field(default_factory=list)
    proposal: PlanProposal | None = None
    proposal_key: tuple | None = None
    model_unreachable: bool = False
    approved: bool = False
    approved_plan: ImportPlan | None = None
    approved_result: ImportResult | None = None
    mode: str = "first_import"  # "first_import" or "reuse" (a saved plan seeded the session)
    based_on_plan_version: int | None = None
    changes: tuple[PlanChange, ...] = ()
    fx_snapshot: FxSnapshot | None = None  # the exchange rate of this run
    fx_error: str | None = None  # why no rate could be obtained automatically

    @property
    def conversion(self) -> ConvertCurrency | None:
        """The plan's currency conversion, if it has one."""
        if self.plan is None:
            return None
        return next((s for s in self.plan.steps if isinstance(s, ConvertCurrency)), None)

    @property
    def columns(self) -> tuple[ColumnDecision, ...]:
        return tuple(self.decisions[index] for index in sorted(self.decisions))

    @property
    def status(self) -> SessionStatus:
        if self.approved:
            return SessionStatus.APPROVED
        if not self.header_confirmed:
            return SessionStatus.HEADER_CHOICE_REQUIRED
        if any(column.role is None for column in self.columns) or self.role_issues:
            return SessionStatus.ROLE_CONFIRMATION_REQUIRED
        if self.questions or self.plan is None:
            return SessionStatus.QUESTIONS_PENDING
        if self.conversion is not None and self.fx_snapshot is None:
            return SessionStatus.FX_RATE_REQUIRED
        return SessionStatus.READY_FOR_PREVIEW

    def add_notice(self, notice: Notice) -> None:
        if notice not in self.notices:
            self.notices.append(notice)
