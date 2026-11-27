"""`ImportFirstTime`: a stateful session that takes a supplier file to an approved plan.

Flow: `start` reads and profiles the file; the header row may need the user
(`choose_header`); a classifier cascade assigns column roles and the user
confirms what is left (`set_roles`); the deterministic builder reports every
plan parameter it cannot resolve and each becomes a closed-option question
(`answer`); `preview` runs the real engine over the data rows; `approve`
freezes plan and result.

A model never decides anything here: its output is only attached to questions
as a suggestion. If a model is unavailable the session simply continues with
the heuristic stage and asks the user more.
"""

import logging
import time
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pricor.application.cascade import UNCALIBRATED_THRESHOLD, ClassifierStage, Stage, run_cascade
from pricor.application.errors import (
    InvalidInputError,
    InvalidOperationError,
    NoAcceptedRowsError,
)
from pricor.application.manage_memory import ManageMemory
from pricor.application.questions import build_questions, decorate, parse_answer, question_for
from pricor.domain.cells import display
from pricor.domain.contract import ContractRecord
from pricor.domain.engine import ImportResult, execute_numbered_rows
from pricor.domain.fingerprint import fingerprint_of
from pricor.domain.fx import MANUAL, FxSnapshot, manual_snapshot
from pricor.domain.fx import FxInvalidRateError
from pricor.domain.plan import PlanValidationError
from pricor.domain.plan_builder import PlanParameters, RoleAssignment, build_plan
from pricor.domain.profile import HEADER_SEARCH_ROWS, RowClass, SheetProfile, profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassification
from pricor.ports.fx_rates import FxError, FxRateProvider
from pricor.ports.import_session import (
    ColumnDecision,
    HeaderCandidate,
    ImportSession,
    Notice,
    PreviewPage,
    PreviewRow,
    PreviewTraceStep,
    SessionStatus,
)
from pricor.ports.approval_unit_of_work import ApprovalUnitOfWork
from pricor.ports.import_session_repository import ImportSessionRepository
from pricor.ports.model_errors import ModelError, ModelTimeoutError, ModelUnavailableError
from pricor.ports.output_format import OutputFormatStore
from pricor.ports.plan_advisor import ParameterId, PlanAdvisor, parse_value, with_answer
from pricor.ports.price_history import ImportedRecord
from pricor.ports.question_model import Suggestion
from pricor.ports.spreadsheet import SpreadsheetReader

__all__ = ["UNCALIBRATED_THRESHOLD", "ClassifierStage", "ImportFirstTime"]

logger = logging.getLogger(__name__)

_MAX_HEADER_CANDIDATES = 8
_CELL_PREVIEW_CHARS = 40
MAX_PREVIEW_LIMIT = 500


def _preview_text(value: Any) -> str:
    return "" if value is None else display(value)


def _header_candidates(rows: Sequence[Sequence[Any]], profile: SheetProfile) -> tuple[HeaderCandidate, ...]:
    """The detected row plus the first rows of the sheet that could plausibly be a header."""
    indexes = [
        index
        for index, row in enumerate(rows[:HEADER_SEARCH_ROWS])
        if sum(1 for cell in row if cell is not None and _preview_text(cell).strip()) >= 2
    ][:_MAX_HEADER_CANDIDATES]
    if profile.header_row is not None and profile.header_row not in indexes:
        indexes = sorted([*indexes[: _MAX_HEADER_CANDIDATES - 1], profile.header_row])
    return tuple(
        HeaderCandidate(
            index,
            index + 1,
            tuple(_preview_text(cell)[:_CELL_PREVIEW_CHARS] for cell in rows[index]),
        )
        for index in indexes
    )


def _record_dict(record: ContractRecord) -> dict[str, str | None]:
    return {
        name: None if value is None else str(value)
        for name, value in vars(record).items()
    }


class ImportFirstTime:
    def __init__(
        self,
        reader: SpreadsheetReader,
        repository: ImportSessionRepository,
        stages: Sequence[Stage],
        advisor: PlanAdvisor | None = None,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        approvals: ApprovalUnitOfWork | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        fx: FxRateProvider | None = None,
        default_fx_rate_type: str = "oficial",
        memory: ManageMemory | None = None,
        memory_top_k: int = 3,
        output_formats: OutputFormatStore | None = None,
    ):
        self._reader = reader
        self._repository = repository
        self._stages = tuple(stages)
        self._advisor = advisor
        self._new_id = id_factory
        self._approvals = approvals
        self._clock = clock
        self._fx = fx
        self._default_fx_rate_type = default_fx_rate_type
        self._memory = memory
        self._memory_top_k = memory_top_k
        self._output_formats = output_formats

    # -- operations ------------------------------------------------------------

    def start(
        self,
        file_path: str | Path,
        supplier_name: str,
        sheet: str | None = None,
        language: str = "en",
        force_first_import: bool = False,
    ) -> ImportSession:
        """Open a session for a file.

        `force_first_import` has no effect here: a first import is all this use case does.
        It exists so callers can use `ReuseSupplierPlan` in its place.
        """
        session = self._new_session(file_path, supplier_name, sheet, language)
        self._begin(session)
        return session

    def _new_session(
        self, file_path: str | Path, supplier_name: str, sheet: str | None, language: str
    ) -> ImportSession:
        if not supplier_name.strip():
            raise InvalidInputError("the supplier name is required")
        path = Path(file_path)
        data = self._reader.read_sheet(path, sheet)
        profile = profile_sheet(data.rows)
        source_notices = (
            (
                Notice(
                    "pdf_vision_extracted",
                    "this PDF was read visually (no structured table was found); "
                    "verify codes and prices in the preview before approving",
                    "pdf_vision",
                ),
            )
            if data.extraction == "pdf_vision"
            else ()
        )
        return ImportSession(
            id=self._new_id(),
            supplier_name=supplier_name.strip(),
            file_name=path.name,
            sheet_name=data.name,
            language=language,
            rows=data.rows,
            profile=profile,
            header_confirmed=profile.header_row is not None and not profile.header_ambiguous,
            header_candidates=_header_candidates(data.rows, profile),
            notices=list(source_notices),
            source_notices=source_notices,
        )

    def _begin(self, session: ImportSession) -> None:
        if session.header_confirmed:
            self._classify(session)
        self._repository.add(session)

    def get(self, session_id: str) -> ImportSession:
        return self._repository.get(session_id)

    def choose_header(self, session_id: str, row_index: int | None) -> ImportSession:
        """Settle the header: a 0-based row index, or `None` for a header-less sheet."""
        session = self._open(session_id)
        try:
            profile = profile_sheet(session.rows, header_row=row_index)
        except ValueError as error:
            raise InvalidInputError(str(error)) from error
        session.profile = profile
        session.header_confirmed = True
        session.answers = {}
        session.ignored_rows = set()
        session.cell_overrides = {}
        session.proposal = None
        session.proposal_key = None
        self._classify(session)
        self._repository.save(session)
        return session

    def set_roles(self, session_id: str, overrides: Mapping[int, ColumnRole]) -> ImportSession:
        session = self._open(session_id)
        if not session.header_confirmed:
            raise InvalidOperationError("choose the header row before assigning roles")
        unknown = sorted(set(overrides) - set(session.decisions))
        if unknown:
            raise InvalidInputError(f"unknown column indexes: {unknown}")
        for index, role in overrides.items():
            current = session.decisions[index]
            session.decisions[index] = replace(
                current,
                role=ColumnRole(role),
                decided_by="user",
                score=1.0,
                rationale="confirmed by the user",
            )
        self._refresh(session)
        self._repository.save(session)
        return session

    def answer(self, session_id: str, question_id: str, option: str) -> ImportSession:
        session = self._open(session_id)
        pending = {q.id.value for q in session.questions}
        answered = {parameter.value for parameter in session.answers}
        question = question_for(ParameterId(question_id)) if question_id in pending | answered else None
        if question is None:
            raise InvalidInputError(f"'{question_id}' is not a pending or answered question")
        parse_answer(question, option)
        session.answers[question.id] = option
        self._refresh(session)
        self._repository.save(session)
        return session

    def preview(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 50,
        query: str = "",
        status: str = "all",
    ) -> PreviewPage:
        if offset < 0:
            raise InvalidInputError("offset must be zero or positive")
        if not 1 <= limit <= MAX_PREVIEW_LIMIT:
            raise InvalidInputError(f"limit must be between 1 and {MAX_PREVIEW_LIMIT}")
        if status not in ("all", "accepted", "rejected"):
            raise InvalidInputError("status must be one of: all, accepted, rejected")
        needle = _fold(query)
        if len(needle) > 200:
            raise InvalidInputError("search query must be at most 200 characters")
        session = self._repository.get(session_id)
        if session.status not in (SessionStatus.READY_FOR_PREVIEW, SessionStatus.APPROVED):
            raise InvalidOperationError(
                f"the session is {session.status.value}; answer the open questions first"
            )
        items = self._preview_rows(session)
        if status != "all":
            items = [row for row in items if row.status == status]
        if needle:
            items = [row for row in items if _row_matches(row, needle)]
        page = tuple(items[offset : offset + limit])
        return PreviewPage(offset, limit, len(items), page, self._totals(session))

    def row_context(self, session_id: str, row_number: int, radius: int = 2) -> dict[str, Any]:
        """Return surrounding rows (`±radius`) around `row_number` with failing column indexes."""
        if not 0 <= radius <= 5:
            raise InvalidInputError("radius must be between 0 and 5")
        session = self._repository.get(session_id)
        if session.status not in (SessionStatus.READY_FOR_PREVIEW, SessionStatus.APPROVED):
            raise InvalidOperationError(
                f"the session is {session.status.value}; answer the open questions first"
            )
        if not 1 <= row_number <= len(session.rows):
            raise InvalidInputError(f"row_number must be between 1 and {len(session.rows)}")

        result = self._execute(session)
        rejected = next((item for item in result.rejected if item.row_number == row_number), None)
        columns_by_header_len = sorted(
            enumerate(session.profile.columns),
            key=lambda pair: len(pair[1].plan_header),
            reverse=True,
        )
        target_columns: list[int] = []
        if rejected is not None:
            for reason in rejected.reasons:
                match = next(
                    (
                        pos
                        for pos, col in columns_by_header_len
                        if reason.startswith(f"{col.plan_header}: ")
                    ),
                    None,
                )
                if match is not None and match not in target_columns:
                    target_columns.append(match)

        class_by_index = {item.index: item.kind.value for item in session.profile.row_classes}
        start = max(0, row_number - 1 - radius)
        end = min(len(session.rows), row_number + radius)
        headers = [col.raw_header or col.plan_header for col in session.profile.columns]
        rows = []
        for idx in range(start, end):
            current_row_number = idx + 1
            effective = self._effective_row(session, current_row_number)
            cells = [
                _preview_text(effective[col.index]) if col.index < len(effective) else ""
                for col in session.profile.columns
            ]
            rows.append(
                {
                    "row_number": current_row_number,
                    "row_class": class_by_index.get(idx, RowClass.DATA.value),
                    "cells": cells,
                    "is_target": current_row_number == row_number,
                    "ignored": current_row_number in session.ignored_rows,
                }
            )
        return {
            "row_number": row_number,
            "headers": headers,
            "column_indexes": [col.index for col in session.profile.columns],
            "target_columns": target_columns,
            "rows": rows,
        }

    def resolve_rows(
        self,
        session_id: str,
        action: str,
        *,
        row_number: int | None = None,
        reason: str | None = None,
        column_index: int | None = None,
        value: str | None = None,
    ) -> dict[str, Any]:
        """Ignore non-product rows or override offending cells, then re-execute the plan."""
        session = self._open(session_id)
        if session.status is not SessionStatus.READY_FOR_PREVIEW:
            raise InvalidOperationError(
                f"the session is {session.status.value}; answer the open questions first"
            )
        result = self._execute(session)
        data_rows = {index + 1 for index in session.profile.indexes_of(RowClass.DATA)}
        valid_columns = {col.index for col in session.profile.columns}

        if action == "ignore_row":
            if row_number is None or row_number not in data_rows:
                raise InvalidInputError("a valid data row_number is required")
            session.ignored_rows.add(row_number)
            affected = 1
        elif action == "ignore_by_reason":
            if not isinstance(reason, str) or not reason.strip():
                raise InvalidInputError("a non-empty reason is required")
            matched = [item.row_number for item in result.rejected if reason in item.reasons]
            session.ignored_rows.update(matched)
            affected = len(matched)
        elif action == "edit_cell":
            if row_number is None or row_number not in data_rows:
                raise InvalidInputError("a valid data row_number is required")
            if column_index is None or column_index not in valid_columns:
                raise InvalidInputError("a valid column_index is required")
            if value is None:
                raise InvalidInputError("value is required")
            session.ignored_rows.discard(row_number)
            session.cell_overrides[(row_number, column_index)] = value
            affected = 1
        elif action == "edit_by_reason":
            if not isinstance(reason, str) or not reason.strip():
                raise InvalidInputError("a non-empty reason is required")
            if column_index is None or column_index not in valid_columns:
                raise InvalidInputError("a valid column_index is required")
            if value is None:
                raise InvalidInputError("value is required")
            matched = [item.row_number for item in result.rejected if reason in item.reasons]
            for r_num in matched:
                session.ignored_rows.discard(r_num)
                session.cell_overrides[(r_num, column_index)] = value
            affected = len(matched)
        elif action == "restore_ignored":
            affected = len(session.ignored_rows)
            session.ignored_rows.clear()
        else:
            raise InvalidInputError(f"unknown resolution action {action!r}")

        session.result = None
        self._execute(session)
        self._repository.save(session)
        return {
            "affected": affected,
            "ignored_count": len(session.ignored_rows),
            "override_count": len(session.cell_overrides),
            "totals": self._totals(session),
        }

    def sample(self, session_id: str, limit: int = 5) -> dict[str, Any]:
        if not 1 <= limit <= 20:
            raise InvalidInputError("limit must be between 1 and 20")
        session = self._repository.get(session_id)
        profile = session.profile
        header = [column.raw_header for column in profile.columns]
        width = len(profile.columns)
        data_indexes = profile.indexes_of(RowClass.DATA)
        if profile.header_row is not None:
            data_indexes = [idx for idx in data_indexes if idx > profile.header_row]
        sampled_indexes = data_indexes[:limit]
        rows = [
            [
                display(session.rows[idx][i])
                if i < len(session.rows[idx]) and session.rows[idx][i] is not None
                else ""
                for i in range(width)
            ]
            for idx in sampled_indexes
        ]
        return {"header": header, "rows": rows}

    def approve(self, session_id: str) -> ImportSession:
        session = self._repository.get(session_id)
        if session.approved:
            return session
        if session.status is not SessionStatus.READY_FOR_PREVIEW:
            raise InvalidOperationError(
                f"the session is {session.status.value}; it cannot be approved yet"
            )
        result = self._execute(session)
        if not result.accepted:
            raise NoAcceptedRowsError(
                "the plan accepts none of the data rows; review the column roles and answers"
            )
        session.approved_plan = session.plan
        session.approved_result = result
        session.approved = True
        if self._output_formats is not None:
            # The download must match what was approved, even if the layout changes later.
            stored = self._output_formats.get()
            session.approved_output_format = stored if stored and stored.state == "confirmed" else None
            session.output_format_frozen = True
        try:
            self._persist_approval(session, result)
        except BaseException:
            # The repository may hand out live objects: undo the freeze so the
            # user can retry.
            session.approved = False
            session.approved_plan = None
            session.approved_result = None
            session.approved_output_format = None
            session.output_format_frozen = False
            raise
        return session

    def _persist_approval(self, session: ImportSession, result: ImportResult) -> None:
        """Without a unit of work only the session is saved; with one, plan, history and
        session are written in a single transaction."""
        if self._approvals is None:
            self._repository.save(session)
            return
        now = self._clock()
        with self._approvals.approval() as transaction:
            transaction.plans.save(
                session.supplier_name, session.plan, fingerprint_of(session.profile, session.sheet_name), now
            )
            transaction.history.record_import(
                session.id,
                session.supplier_name,
                now,
                [ImportedRecord(item.row_number, item.record) for item in result.accepted],
                fx=session.fx_snapshot if session.conversion is not None else None,
            )
            transaction.sessions.save(session)

    def set_manual_rate(self, session_id: str, rate_text: str) -> ImportSession:
        """Use a rate the user typed in for this run (any plan rate type accepts it)."""
        session = self._open(session_id)
        step = session.conversion
        if step is None:
            raise InvalidOperationError("this import does not convert currency")
        try:
            snapshot = manual_snapshot(
                rate_text, step.from_currency, step.to_currency, step.side, self._clock()
            )
        except FxInvalidRateError as error:
            raise InvalidInputError(str(error)) from error
        session.fx_snapshot, session.fx_error, session.result = snapshot, None, None
        self._repository.save(session)
        return session

    def refresh_fx(self, session_id: str) -> ImportSession:
        """Ask the live source for the plan's rate again, replacing the run's snapshot."""
        session = self._open(session_id)
        if session.conversion is None:
            raise InvalidOperationError("this import does not convert currency")
        session.fx_snapshot, session.result = None, None
        self._ensure_fx(session)
        self._repository.save(session)
        return session

    # -- internals -------------------------------------------------------------

    def _ensure_fx(self, session: ImportSession) -> None:
        """Give the run the exchange rate its plan needs: kept, fetched fresh, or still missing.

        Nothing is guessed: with no usable rate the session stays in `fx_rate_required`.
        """
        step = session.conversion
        current = session.fx_snapshot
        if step is None:
            session.fx_snapshot, session.fx_error = None, None
            return
        pair = (step.from_currency, step.to_currency)
        if current is not None and (current.from_currency, current.to_currency) == pair:
            if current.source == MANUAL:
                session.fx_snapshot = replace(current, side=step.side)
                return
            if (current.rate_type, current.side) == (step.rate_type, step.side):
                return
        session.fx_snapshot, session.fx_error = None, None
        session.result = None
        if step.rate_type == MANUAL:
            return  # the user types the rate; the live source is never asked
        if self._fx is None:
            session.fx_error = "no exchange-rate source is configured; enter a rate"
            return
        try:
            session.fx_snapshot = self._fx.snapshot(*pair, step.rate_type, step.side)
        except FxError as error:
            session.fx_error = str(error)

    def _with_default_fx(self, questions: tuple) -> tuple:
        """Offer the configured default rate type on the conversion question, as a suggestion."""
        return tuple(
            replace(
                question,
                suggestion=Suggestion(
                    f"{self._default_fx_rate_type}:venta", 1.0, suggested_by="setting", calibrated=True
                ),
            )
            if question.id is ParameterId.FX_CONVERSION and question.suggestion is None
            else question
            for question in questions
        )

    def _open(self, session_id: str) -> ImportSession:
        session = self._repository.get(session_id)
        if session.approved:
            raise InvalidOperationError("the session is approved and can no longer change")
        return session

    def _classify(self, session: ImportSession) -> None:
        if not session.profile.columns:
            raise InvalidInputError("the sheet has no data columns")
        session.decisions, notices, unreachable = run_cascade(self._stages, session.profile)
        session.notices = [*session.source_notices, *notices]
        session.model_unreachable = unreachable
        session.header_confirmed = True
        self._refresh(session)

    def _refresh(self, session: ImportSession) -> None:
        """Rebuild plan and questions from the current roles and answers."""
        session.plan = None
        session.result = None
        session.questions = ()
        session.role_issues = ()
        if any(column.role is None for column in session.columns):
            return

        assignments = [
            RoleAssignment(column, session.decisions[column.index].role)
            for column in session.profile.columns
        ]
        parameters = PlanParameters(
            supplier=session.supplier_name,
            confirmations=tuple(
                f"{parameter.value}={token} (user)" for parameter, token in session.answers.items()
            ),
        )
        for question_id, token in session.answers.items():
            parameters = with_answer(parameters, question_id, parse_value(question_id, token))

        try:
            built = build_plan(assignments, parameters)
        except PlanValidationError as error:
            session.role_issues = tuple(error.problems)
            return
        if built.plan is not None:
            session.plan = built.plan
            self._ensure_fx(session)
            return
        questions, issues = build_questions(built.unresolved)
        session.role_issues = issues
        if issues:
            return  # questions wait until the column roles are consistent
        if questions:
            self._ensure_proposal(session, assignments)
        session.questions = self._with_default_fx(decorate(questions, session.proposal))

    def _ensure_proposal(self, session: ImportSession, assignments: list[RoleAssignment]) -> None:
        if self._advisor is None or session.model_unreachable:
            return
        key = tuple((item.column.index, item.role) for item in assignments)
        if session.proposal_key == key:
            return
        session.proposal_key = key
        session.proposal = None
        classifications = [
            ColumnClassification(
                index=item.column.index,
                header=item.column.raw_header,
                role=item.role,
                score=session.decisions[item.column.index].score,
                rationale=session.decisions[item.column.index].rationale,
            )
            for item in assignments
        ]
        memories = []
        if self._memory is not None:
            query = " ".join(
                (session.supplier_name, *(column.header for column in session.profile.columns))
            )
            try:
                memories = self._memory.relevant(query, self._memory_top_k)
            except Exception as error:
                session.add_notice(
                    Notice(
                        "memory_unavailable",
                        f"semantic memory could not be retrieved ({type(error).__name__}): {error}",
                        "memory",
                    )
                )
        started = time.perf_counter()
        try:
            proposal = self._advisor.propose(
                session.profile,
                classifications,
                memory_context=[item.text for item in memories] or None,
                language=session.language,
            )
            session.proposal = replace(
                proposal, memory_ids=tuple(item.id for item in memories)
            )
        except ModelError as error:
            if isinstance(error, ModelUnavailableError | ModelTimeoutError):
                session.model_unreachable = True
            logger.warning("plan advisor failed (%s): %s", type(error).__name__, error)
            session.add_notice(
                Notice(
                    "model_unavailable",
                    f"the plan advisor could not help ({type(error).__name__}): {error}",
                    "advisor",
                )
            )
        finally:
            logger.info("plan advisor: %.2fs", time.perf_counter() - started)

    # -- preview ---------------------------------------------------------------

    @staticmethod
    def _effective_row(session: ImportSession, row_number: int) -> tuple[Any, ...]:
        raw = session.rows[row_number - 1]
        if not session.cell_overrides:
            return tuple(raw)
        row_edits = {
            col: val
            for (r_num, col), val in session.cell_overrides.items()
            if r_num == row_number
        }
        if not row_edits:
            return tuple(raw)
        width = max(len(raw), max(row_edits) + 1)
        cells = [raw[i] if i < len(raw) else None for i in range(width)]
        for col, val in row_edits.items():
            cells[col] = val
        return tuple(cells)

    def _execute(self, session: ImportSession):
        if session.result is None:
            profile = session.profile
            headers = [column.plan_header for column in profile.columns]
            data = [
                (index + 1, self._effective_row(session, index + 1))
                for index in profile.indexes_of(RowClass.DATA)
                if (index + 1) not in session.ignored_rows
            ]
            session.result = execute_numbered_rows(
                session.plan, headers, data, session.fx_snapshot
            )
        return session.result

    def _preview_rows(self, session: ImportSession) -> list[PreviewRow]:
        result = self._execute(session)
        rows: list[PreviewRow] = []
        for item in result.accepted:
            rows.append(
                PreviewRow(
                    item.row_number,
                    "accepted",
                    self._original(session, item.row_number),
                    tuple(PreviewTraceStep(step.step, str(step.value)) for step in item.trace),
                    _record_dict(item.record),
                    (),
                )
            )
        for item in result.rejected:
            rows.append(
                PreviewRow(
                    item.row_number,
                    "rejected",
                    self._original(session, item.row_number),
                    (),
                    None,
                    item.reasons,
                )
            )
        return sorted(rows, key=lambda row: row.row_number)

    @staticmethod
    def _original(session: ImportSession, row_number: int) -> tuple[str, ...]:
        return tuple(
            _preview_text(cell) for cell in ImportFirstTime._effective_row(session, row_number)
        )

    def _totals(self, session: ImportSession) -> dict[str, Any]:
        result = self._execute(session)
        reasons: dict[str, int] = {}
        for item in result.rejected:
            for reason in item.reasons:
                reasons[reason] = reasons.get(reason, 0) + 1
        skipped = {
            kind.value: len(session.profile.indexes_of(kind))
            for kind in (RowClass.EMPTY, RowClass.TOTAL, RowClass.SECTION, RowClass.PREAMBLE)
        }
        if session.ignored_rows:
            skipped["ignored_by_user"] = len(session.ignored_rows)
        return {
            "data_rows": len(result.accepted) + len(result.rejected),
            "accepted": len(result.accepted),
            "rejected": len(result.rejected),
            "rejected_rows": [
                {"row_number": item.row_number, "reasons": list(item.reasons)}
                for item in sorted(result.rejected, key=lambda row: row.row_number)
            ],
            "reason_counts": dict(sorted(reasons.items(), key=lambda pair: -pair[1])),
            "skipped_rows": skipped,
        }


def _fold(text: str) -> str:
    """Accent- and case-insensitive search key."""
    decomposed = unicodedata.normalize("NFKD", text.strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _row_matches(row: PreviewRow, needle: str) -> bool:
    if row.record:
        for key in ("supplier_code", "description"):
            value = row.record.get(key)
            if value and needle in _fold(str(value)):
                return True
    return any(needle in _fold(cell) for cell in row.original)
