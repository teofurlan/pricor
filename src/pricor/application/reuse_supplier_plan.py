"""`ReuseSupplierPlan`: start an import from the plan a supplier already approved.

It is an `ImportFirstTime` whose `start` looks for the supplier's latest saved plan. When
there is one, the new file is profiled and its fingerprint compared with the one the plan
was approved against; the session is then pre-filled from the plan instead of from scratch.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from pricor.application.cascade import ClassifierStage, run_cascade
from pricor.application.import_first_time import ImportFirstTime
from pricor.domain.fingerprint import FingerprintComparison, compare_fingerprint
from pricor.domain.plan_roles import column_roles
from pricor.domain.roles import ColumnRole
from pricor.ports.approval_unit_of_work import ApprovalUnitOfWork
from pricor.ports.import_session import ColumnDecision, ImportSession, PlanChange
from pricor.ports.import_session_repository import ImportSessionRepository
from pricor.ports.plan_advisor import ParameterId, PlanAdvisor
from pricor.ports.plan_repository import PlanRepository, StoredPlan
from pricor.ports.spreadsheet import SpreadsheetReader

SAVED_PLAN = "saved_plan"  # `decided_by` of a column whose role came from the saved plan
FIRST_IMPORT = "first_import"
REUSE = "reuse"

_USER_MARK = " (user)"


def _saved_answers(plan_confirmations: Sequence[str]) -> dict[ParameterId, str]:
    """The answers the user gave when the plan was approved, as `parameter=token (user)` texts."""
    answers: dict[ParameterId, str] = {}
    for text in plan_confirmations:
        body = text.removesuffix(_USER_MARK)
        name, separator, token = body.partition("=")
        if not separator or body == text:
            continue
        try:
            answers[ParameterId(name)] = token
        except ValueError:
            continue
    return answers


class ReuseSupplierPlan(ImportFirstTime):
    def __init__(
        self,
        reader: SpreadsheetReader,
        repository: ImportSessionRepository,
        stages: Sequence[ClassifierStage],
        advisor: PlanAdvisor | None = None,
        *,
        plans: PlanRepository,
        id_factory: Callable[[], str] | None = None,
        approvals: ApprovalUnitOfWork | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        extra = {}
        if id_factory is not None:
            extra["id_factory"] = id_factory
        if clock is not None:
            extra["clock"] = clock
        super().__init__(reader, repository, stages, advisor, approvals=approvals, **extra)
        self._plans = plans

    def start(
        self,
        file_path: str | Path,
        supplier_name: str,
        sheet: str | None = None,
        language: str = "en",
        force_first_import: bool = False,
    ) -> ImportSession:
        session = self._new_session(file_path, supplier_name, sheet, language)
        stored = None if force_first_import else self._plans.latest_for(session.supplier_name)
        if stored is not None:
            session.mode = REUSE
            session.based_on_plan_version = stored.version
        self._begin(session)
        return session

    # -- internals -------------------------------------------------------------

    def _saved_plan(self, session: ImportSession) -> StoredPlan | None:
        for stored in self._plans.versions_for(session.supplier_name):
            if stored.version == session.based_on_plan_version:
                return stored
        return None

    def _classify(self, session: ImportSession) -> None:
        stored = self._saved_plan(session) if session.mode == REUSE else None
        if stored is None:
            session.mode, session.based_on_plan_version, session.changes = FIRST_IMPORT, None, ()
            super()._classify(session)
            return

        profile = session.profile
        comparison = compare_fingerprint(stored.fingerprint, profile, session.sheet_name, stored.plan)
        roles = column_roles(stored.plan)
        version = stored.version

        decisions: dict[int, ColumnDecision] = {}
        for change in (*comparison.unchanged, *comparison.moved):
            column = profile.columns[change.new_index]
            moved = change.saved_index != change.new_index
            decisions[column.index] = ColumnDecision(
                column.index,
                column.plan_header,
                roles.get(change.saved_index, ColumnRole.IGNORE),
                SAVED_PLAN,
                1.0,
                f"moved from column {change.saved_index + 1} to {change.new_index + 1} "
                f"since plan v{version}"
                if moved
                else f"unchanged since plan v{version}",
            )
        rest = tuple(column for column in profile.columns if column.index not in decisions)
        if rest:
            cascaded, notices, unreachable = run_cascade(
                self._stages, replace(profile, columns=rest)
            )
            decisions.update(cascaded)
            session.notices = list(notices)
            session.model_unreachable = unreachable
        session.decisions = decisions
        session.changes = _changes(comparison, roles)
        session.answers = _saved_answers(stored.plan.confirmations)
        session.header_confirmed = True
        self._refresh(session)

    def _refresh(self, session: ImportSession) -> None:
        super()._refresh(session)
        if session.mode != REUSE:
            return
        assigned = {column.role for column in session.columns}
        orphaned = tuple(
            _orphan_issue(change, session.based_on_plan_version)
            for change in session.changes
            if change.kind == "missing"
            and change.used_by_plan
            and change.role == ColumnRole.DISCOUNT.value
            and ColumnRole.DISCOUNT not in assigned
        )
        if orphaned:
            # Without a discount column the builder would simply leave the rule out; dropping
            # a rule that lowered every cost is not something to do unasked.
            session.role_issues = (*session.role_issues, *orphaned)
            session.plan = None
            session.result = None
            session.questions = ()


def _orphan_issue(change: PlanChange, version: int | None) -> str:
    return (
        f"the discount column '{change.header}' that plan v{version} applies is no longer in "
        "the file; assign the discount role to another column or start again as a first import"
    )


def _changes(comparison: FingerprintComparison, roles: dict[int, ColumnRole]) -> tuple[PlanChange, ...]:
    def role_of(index: int | None) -> str | None:
        role = roles.get(index) if index is not None else None
        return None if role is None else role.value

    changes: list[PlanChange] = []
    if comparison.sheet_change is not None:
        old, new = comparison.sheet_change
        changes.append(PlanChange("sheet_changed", old_value=old, new_value=new))
    if comparison.header_row_change is not None:
        old_row, new_row = comparison.header_row_change
        changes.append(PlanChange("header_row_changed", old_index=old_row, new_index=new_row))
    for kind, group in (
        ("moved", comparison.moved),
        ("retyped", comparison.retyped),
        ("new", comparison.new),
        ("missing", comparison.missing),
    ):
        changes.extend(
            PlanChange(
                kind,
                item.header,
                item.saved_index,
                item.new_index,
                item.saved_type,
                item.new_type,
                item.used_by_plan,
                role_of(item.saved_index),
            )
            for item in group
        )
    return tuple(changes)
