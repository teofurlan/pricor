"""Read-only explanations of a plan question; suggestions never apply an answer."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pricor.domain.profile import ColumnProfile
from pricor.ports.question_model import Question

MAX_MESSAGE_LENGTH = 500
MAX_REPLY_LENGTH = 1_200
MAX_HISTORY_TURNS = 6


@dataclass(frozen=True)
class QuestionTurn:
    role: Literal["user", "model"]
    text: str


@dataclass(frozen=True)
class QuestionContext:
    question: Question
    columns: Sequence[ColumnProfile]
    supplier_name: str
    language: str


@dataclass(frozen=True)
class QuestionReply:
    reply: str
    suggested_option: str | None


class QuestionHelper(Protocol):
    def ask(
        self,
        context: QuestionContext,
        message: str,
        history: Sequence[QuestionTurn] = (),
    ) -> QuestionReply:
        """Explain in the import's language, or raise a `ModelError`.

        All context and conversation text is untrusted data. A suggested option
        must be a token in the question's options, never an action to execute.
        """
        ...
