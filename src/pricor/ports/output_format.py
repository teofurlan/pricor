"""Store-wide output template and closed, declarative column sources.

Sources are data, never expressions. Proposals do not become active until the
user confirms every column. Field order matches the complete products file.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pricor.ports.exporter import (
    CONTRACT_COLUMNS,
    CONVERTED_COLUMNS,
    TRACEABILITY_COLUMNS,
    Exporter,
    ImportExport,
)

OUTPUT_FIELDS = CONTRACT_COLUMNS + CONVERTED_COLUMNS + TRACEABILITY_COLUMNS


class OutputFormatNotFoundError(Exception):
    """There is no saved output format."""


def validate_source(source: str) -> str:
    """Validate without coercion or evaluating any part of the source."""
    if isinstance(source, str):
        if source == "empty" or source in {f"field:{name}" for name in OUTPUT_FIELDS}:
            return source
        if source.startswith("constant:"):
            text = source.removeprefix("constant:")
            if text.strip() and 1 <= len(text) <= 200:
                return source
    raise ValueError("source must be field:<allowed field>, empty, or constant:<1–200 characters>")


@dataclass(frozen=True)
class TemplateColumn:
    index: int
    name: str
    samples: tuple[str, ...]


@dataclass(frozen=True)
class OutputProposal:
    source: str
    proposed_by: str
    confidence: float


@dataclass(frozen=True)
class OutputColumn:
    index: int
    name: str
    samples: tuple[str, ...]
    proposal: OutputProposal
    source: str | None = None


@dataclass(frozen=True)
class OutputFormat:
    name: str
    state: str
    columns: tuple[OutputColumn, ...]


class OutputFormatProposer(Protocol):
    def propose(self, columns: Sequence[TemplateColumn]) -> tuple[OutputProposal, ...]: ...


class OutputFormatStore(Protocol):
    def get(self) -> OutputFormat | None: ...

    def save(self, output_format: OutputFormat) -> None: ...

    def delete(self) -> None: ...


class OutputFormatExporter(Exporter, Protocol):
    def export_formatted(self, data: ImportExport, output_format: OutputFormat) -> bytes:
        """Render products using a confirmed output format; keep rejections unchanged."""
        ...
