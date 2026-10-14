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

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from pricor.application.cascade import UNCALIBRATED_THRESHOLD, ClassifierStage, run_cascade
from pricor.application.errors import InvalidInputError, InvalidOperationError
from pricor.application.import_session import (
    ColumnDecision,
    HeaderCandidate,
    ImportSession,
    Notice,
    PreviewPage,
    PreviewRow,
    PreviewTraceStep,
    SessionStatus,
)
from pricor.application.questions import build_questions, decorate, parse_answer, question_for
from pricor.domain.cells import display
from pricor.domain.contract import ContractRecord
from pricor.domain.engine import execute_numbered_rows
from pricor.domain.plan import PlanValidationError
from pricor.domain.plan_builder import PlanParameters, RoleAssignment, build_plan
from pricor.domain.profile import HEADER_SEARCH_ROWS, RowClass, SheetProfile, profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassification
from pricor.ports.import_session_repository import ImportSessionRepository
from pricor.ports.model_errors import ModelError, ModelTimeoutError, ModelUnavailableError
from pricor.ports.plan_advisor import ParameterId, PlanAdvisor, parse_value, with_answer
from pricor.ports.spreadsheet import SpreadsheetReader

__all__ = ["UNCALIBRATED_THRESHOLD", "ClassifierStage", "ImportFirstTime"]

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
        stages: Sequence[ClassifierStage],
        advisor: PlanAdvisor | None = None,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ):
        self._reader = reader
        self._repository = repository
        self._stages = tuple(stages)
        self._advisor = advisor
        self._new_id = id_factory

    # -- operations ------------------------------------------------------------

    def start(
        self,
        file_path: str | Path,
        supplier_name: str,
        sheet: str | None = None,
        language: str = "en",
    ) -> ImportSession:
        if not supplier_name.strip():
            raise InvalidInputError("the supplier name is required")
        path = Path(file_path)
        data = self._reader.read_sheet(path, sheet)
        profile = profile_sheet(data.rows)
        session = ImportSession(
            id=self._new_id(),
            supplier_name=supplier_name.strip(),
            file_name=path.name,
            sheet_name=data.name,
            language=language,
            rows=data.rows,
            profile=profile,
            header_confirmed=profile.header_row is not None and not profile.header_ambiguous,
            header_candidates=_header_candidates(data.rows, profile),
        )
        if session.header_confirmed:
            self._classify(session)
        self._repository.add(session)
        return session

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

    def preview(self, session_id: str, offset: int = 0, limit: int = 50) -> PreviewPage:
        if offset < 0:
            raise InvalidInputError("offset must be zero or positive")
        if not 1 <= limit <= MAX_PREVIEW_LIMIT:
            raise InvalidInputError(f"limit must be between 1 and {MAX_PREVIEW_LIMIT}")
        session = self._repository.get(session_id)
        if session.status not in (SessionStatus.READY_FOR_PREVIEW, SessionStatus.APPROVED):
            raise InvalidOperationError(
                f"the session is {session.status.value}; answer the open questions first"
            )
        items = self._preview_rows(session)
        page = tuple(items[offset : offset + limit])
        return PreviewPage(offset, limit, len(items), page, self._totals(session))

    def approve(self, session_id: str) -> ImportSession:
        session = self._repository.get(session_id)
        if session.approved:
            return session
        if session.status is not SessionStatus.READY_FOR_PREVIEW:
            raise InvalidOperationError(
                f"the session is {session.status.value}; it cannot be approved yet"
            )
        session.approved_plan = session.plan
        session.approved_result = self._execute(session)
        session.approved = True
        self._repository.save(session)
        return session

    # -- internals -------------------------------------------------------------

    def _open(self, session_id: str) -> ImportSession:
        session = self._repository.get(session_id)
        if session.approved:
            raise InvalidOperationError("the session is approved and can no longer change")
        return session

    def _classify(self, session: ImportSession) -> None:
        if not session.profile.columns:
            raise InvalidInputError("the sheet has no data columns")
        session.decisions, notices, unreachable = run_cascade(self._stages, session.profile)
        session.notices = list(notices)
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
            return
        questions, issues = build_questions(built.unresolved)
        session.role_issues = issues
        if questions and not issues:
            self._ensure_proposal(session, assignments)
            questions = decorate(questions, session.proposal)
        session.questions = questions

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
        try:
            session.proposal = self._advisor.propose(
                session.profile, classifications, language=session.language
            )
        except ModelError as error:
            if isinstance(error, ModelUnavailableError | ModelTimeoutError):
                session.model_unreachable = True
            session.add_notice(
                Notice(
                    "model_unavailable",
                    f"the plan advisor could not help ({type(error).__name__}): {error}",
                    "advisor",
                )
            )

    # -- preview ---------------------------------------------------------------

    def _execute(self, session: ImportSession):
        if session.result is None:
            profile = session.profile
            headers = [column.plan_header for column in profile.columns]
            data = [(index + 1, session.rows[index]) for index in profile.indexes_of(RowClass.DATA)]
            session.result = execute_numbered_rows(session.plan, headers, data)
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
        return tuple(_preview_text(cell) for cell in session.rows[row_number - 1])

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
