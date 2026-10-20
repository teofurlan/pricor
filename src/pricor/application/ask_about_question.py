"""Read-only help for an open or previously answered import question."""

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import replace

from pricor.application.errors import InvalidInputError, QuestionNotFoundError
from pricor.application.questions import build_questions, decorate, question_for
from pricor.domain.plan_builder import PlanParameters, RoleAssignment, build_plan
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session import ImportSession
from pricor.ports.model_errors import ModelUnavailableError
from pricor.ports.plan_advisor import ParameterId, parse_value, with_answer
from pricor.ports.question_helper import (
    MAX_HISTORY_TURNS,
    MAX_MESSAGE_LENGTH,
    MAX_REPLY_LENGTH,
    QuestionContext,
    QuestionHelper,
    QuestionReply,
    QuestionTurn,
)
from pricor.ports.question_model import Question

_RELEVANT_ROLES = {
    ParameterId.NUMBER_FORMAT: {R.COST_PRICE},
    ParameterId.PRICE_INCLUDES_VAT: {R.COST_PRICE, R.VAT_RATE},
    ParameterId.VAT_RATE: {R.COST_PRICE, R.VAT_RATE},
    ParameterId.PRICE_IS_PER_PACK: {R.COST_PRICE, R.UNITS_PER_PACK},
    ParameterId.UNITS_PER_PACK: {R.COST_PRICE, R.UNITS_PER_PACK},
    ParameterId.DISCOUNTS: {R.COST_PRICE, R.DISCOUNT},
    ParameterId.CURRENCY: {R.COST_PRICE, R.CURRENCY},
    ParameterId.FX_CONVERSION: {R.COST_PRICE, R.CURRENCY},
}


def _question(session: ImportSession, question_id: str) -> Question:
    pending = next((q for q in session.questions if q.id.value == question_id), None)
    if pending is not None:
        return pending
    try:
        parameter = ParameterId(question_id)
    except ValueError:
        parameter = None
    base = None if parameter is None else question_for(parameter)
    if base is None or parameter not in session.answers:
        raise QuestionNotFoundError(f"session {session.id!r} has no question {question_id!r}")

    # Answered questions leave session.questions. Rebuild without that answer
    # to recover the builder's reason and dynamic options, without refreshing
    # or saving the session (which would also run advisors or FX providers).
    if all(column.role is not None for column in session.columns):
        parameters = PlanParameters(supplier=session.supplier_name)
        for answered, token in session.answers.items():
            if answered != parameter:
                parameters = with_answer(parameters, answered, parse_value(answered, token))
        assignments = [
            RoleAssignment(column, session.decisions[column.index].role)
            for column in session.profile.columns
        ]
        built = build_plan(assignments, parameters)
        questions, _ = build_questions(built.unresolved)
        base = next((q for q in questions if q.id == parameter), base)
    if not base.reason:
        base = replace(base, reason="Previously answered in this import.")
    return decorate((base,), session.proposal)[0]


class AskAboutQuestion:
    def __init__(
        self,
        get_session: Callable[[str], ImportSession],
        helper: QuestionHelper | None,
    ):
        self._get_session = get_session
        self._helper = helper

    def execute(
        self,
        session_id: str,
        question_id: str,
        message: str,
        history: Sequence[QuestionTurn] = (),
    ) -> QuestionReply:
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= MAX_MESSAGE_LENGTH:
            raise InvalidInputError(f"message must have 1 to {MAX_MESSAGE_LENGTH} characters after trimming")
        if len(history) > MAX_HISTORY_TURNS or any(
            turn.role not in ("user", "model")
            or not isinstance(turn.text, str)
            or len(turn.text) > MAX_REPLY_LENGTH
            for turn in history
        ):
            raise InvalidInputError(
                f"history must contain at most {MAX_HISTORY_TURNS} user/model turns, "
                f"each at most {MAX_REPLY_LENGTH} characters"
            )
        session = self._get_session(session_id)
        question = _question(session, question_id)
        if self._helper is None:
            raise ModelUnavailableError("question helper is not configured")
        indices = {
            column.index for column in session.columns
            if column.role in _RELEVANT_ROLES[question.id]
        }
        if question.suggestion is not None:
            indices.update(item.column_index for item in question.suggestion.evidence)
        if session.proposal is not None:
            for proposed in session.proposal.questions:
                if proposed.id == question.id:
                    indices.update(item.column_index for item in proposed.evidence)
        context = QuestionContext(
            question=question,
            columns=tuple(c for c in session.profile.columns if c.index in indices),
            supplier_name=session.supplier_name,
            language=session.language,
        )
        # A helper receives only detached context, never the session or a store.
        return self._helper.ask(deepcopy(context), message.strip(), tuple(history))
