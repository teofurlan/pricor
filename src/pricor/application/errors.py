"""Typed failures of the application layer. Messages are safe to show to the user."""


class ApplicationError(Exception):
    """Base class for use-case failures."""


class InvalidInputError(ApplicationError):
    """The request carries a value the session cannot accept."""


class InvalidOperationError(ApplicationError):
    """The operation is not allowed in the session's current state."""


class NoAcceptedRowsError(InvalidOperationError):
    """Approval was requested but the plan accepts none of the data rows."""


class NoPreviousImportError(InvalidOperationError):
    """A report needs an earlier approved import of the same supplier and there is none."""
