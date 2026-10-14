"""Typed failures of model-backed adapters.

Anything a model returns that cannot be trusted ends as one of these errors.
Callers surface them to the user; nothing is repaired or guessed.
"""


class ModelError(Exception):
    """Base class. The message is safe to show to the user."""


class ModelUnavailableError(ModelError):
    """The model server cannot be reached, or refused the request."""


class ModelTimeoutError(ModelError):
    """The model did not answer within the configured time."""


class ModelInvalidJsonError(ModelError):
    """The reply is not the JSON object that was requested."""


class ModelSchemaError(ModelError):
    """The reply is JSON but violates the schema or the closed vocabularies."""
