"""Explicit creation and maintenance of semantic memories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pricor.application.errors import (
    AcceptedSuggestionConflictError,
    EmbedderUnavailableError,
    QuestionNotFoundError,
)
from pricor.application.questions import decorate, question_for
from pricor.ports.embedder import Embedder
from pricor.ports.import_session import ImportSession
from pricor.ports.memory import Memory, MemorySource, MemoryStore
from pricor.ports.model_errors import ModelError, ModelSchemaError
from pricor.ports.plan_advisor import ParameterId

MAX_MEMORY_TEXT_LENGTH = 1_000


class InvalidMemoryTextError(ValueError):
    """A note is empty after trimming or exceeds the supported size."""


def _validated_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise InvalidMemoryTextError("memory text must not be empty")
    if len(normalized) > MAX_MEMORY_TEXT_LENGTH:
        raise InvalidMemoryTextError(
            f"memory text must be at most {MAX_MEMORY_TEXT_LENGTH:,} characters"
        )
    return normalized


class ManageMemory:
    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder,
        get_session: Callable[[str], ImportSession],
    ):
        self._store = store
        self._embedder = embedder
        self._get_session = get_session

    def create_note(self, text: str, supplier_name: str | None = None) -> Memory:
        return self._create(text, supplier_name, "user_note")

    def create_accepted_suggestion(
        self, session_id: str, question_id: str
    ) -> Memory:
        session = self._get_session(session_id)
        question = next(
            (item for item in session.questions if item.id.value == question_id), None
        )
        if question is None:
            try:
                parameter = ParameterId(question_id)
            except ValueError:
                parameter = None
            base = None if parameter is None else question_for(parameter)
            if base is None or parameter not in session.answers:
                raise QuestionNotFoundError(
                    f"session {session_id!r} has no question {question_id!r}"
                )
            # Answered questions leave the pending tuple. Rebuild the deterministic
            # question and restore its Gemma proposal from the session snapshot.
            question = decorate((base,), session.proposal)[0]
            if question.suggestion is not None and question.suggestion.suggested_by == "model":
                question = replace(
                    question,
                    suggestion=replace(question.suggestion, suggested_by="gemma"),
                )
        suggestion = question.suggestion
        answer = session.answers.get(question.id)
        if (
            suggestion is None
            or suggestion.suggested_by != "gemma"
            or answer != suggestion.option
        ):
            raise AcceptedSuggestionConflictError(
                "the session answer must accept the option suggested by Gemma"
            )
        option = next((item for item in question.options if item.token == answer), None)
        if option is None:
            raise AcceptedSuggestionConflictError(
                "the accepted Gemma suggestion has no labeled question option"
            )
        text = f"{session.supplier_name}: {question.text.en} -> {option.label.en}"
        return self._create(text, session.supplier_name, "accepted_suggestion")

    def list(self) -> list[Memory]:
        return self._store.list()

    def edit(self, memory_id: str, text: str) -> Memory:
        normalized = _validated_text(text)
        current = self._store.get(memory_id)
        changed = Memory(
            current.id,
            normalized,
            current.supplier_name,
            current.source,
            current.created_at,
            datetime.now(UTC),
        )
        self._store.update(changed, self._embed_one(normalized))
        return changed

    def delete(self, memory_id: str) -> None:
        self._store.delete(memory_id)

    def relevant(self, query: str, k: int) -> list[Memory]:
        normalized = query.strip()
        if not normalized or k <= 0:
            return []
        return self._store.search(self._embed_one(normalized), k)

    def _create(
        self, text: str, supplier_name: str | None, source: MemorySource
    ) -> Memory:
        normalized = _validated_text(text)
        now = datetime.now(UTC)
        memory = Memory(str(uuid4()), normalized, supplier_name, source, now, now)
        self._store.add(memory, self._embed_one(normalized))
        return memory

    def _embed_one(self, text: str) -> list[float]:
        try:
            vectors = self._embedder.embed([text])
            if len(vectors) != 1:
                raise ModelSchemaError("the embedding model did not return one vector")
            return vectors[0]
        except ModelError as error:
            raise EmbedderUnavailableError(str(error)) from error
