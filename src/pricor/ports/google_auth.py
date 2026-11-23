"""Google ID token verification port."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GoogleIdentity:
    """Verified identity extracted from a Google ID token."""

    sub: str
    email: str


class InvalidGoogleTokenError(Exception):
    """Raised when a Google ID token is missing, malformed, or fails verification."""


class GoogleTokenVerifier(Protocol):
    """Verifies a Google Identity Services ID token credential."""

    def verify(self, credential: str) -> GoogleIdentity:
        """Return the verified identity or raise `InvalidGoogleTokenError`."""
        ...
