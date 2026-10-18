"""Port for turning untrusted text into semantic vectors."""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """A model-backed batch embedder."""

    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one finite vector for each input text."""
        ...

