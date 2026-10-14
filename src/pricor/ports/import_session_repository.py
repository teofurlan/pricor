"""Port for storing first-import sessions between requests.

The in-memory adapter keeps live objects; a persistent adapter (SQLite) must
store and restore the same `ImportSession` state. The use case always calls
`save` after it changes a session and `get` before it reads one, so an adapter
may hand out copies.
"""

from typing import Protocol

from pricor.ports.import_session import ImportSession


class SessionNotFoundError(Exception):
    """No session with that id exists."""


class ImportSessionRepository(Protocol):
    def add(self, session: ImportSession) -> None:
        """Store a new session."""
        ...

    def get(self, session_id: str) -> ImportSession:
        """Return the session or raise `SessionNotFoundError`."""
        ...

    def save(self, session: ImportSession) -> None:
        """Persist the changed state of an existing session."""
        ...
