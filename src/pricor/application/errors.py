"""Typed failures of the application layer. Messages are safe to show to the user."""


class ApplicationError(Exception):
    """Base class for use-case failures."""


class InvalidInputError(ApplicationError):
    """The request carries a value the session cannot accept."""


class InvalidOperationError(ApplicationError):
    """The operation is not allowed in the session's current state."""
