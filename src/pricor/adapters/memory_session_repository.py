"""In-memory `ImportSessionRepository` (sessions live as long as the process)."""

from pricor.ports.import_session import ImportSession
from pricor.ports.import_session_repository import SessionNotFoundError


class InMemoryImportSessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, ImportSession] = {}

    def add(self, session: ImportSession) -> None:
        self._sessions[session.id] = session

    def get(self, session_id: str) -> ImportSession:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(f"no import session {session_id!r}") from None

    def save(self, session: ImportSession) -> None:
        if session.id not in self._sessions:
            raise SessionNotFoundError(f"no import session {session.id!r}")
        self._sessions[session.id] = session
