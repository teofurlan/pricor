"""Store-wide output template and closed, declarative column sources.

Sources are data, never expressions. Proposals do not become active until the
user confirms every column. Field order matches the complete products file.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pricor.ports.exporter import (
    CONTRACT_COLUMNS,
    CONVERTED_COLUMNS,
    TRACEABILITY_COLUMNS,
    Exporter,
    ImportExport,
)

OUTPUT_FIELDS = CONTRACT_COLUMNS + CONVERTED_COLUMNS + TRACEABILITY_COLUMNS

OUTPUT_KINDS = ("text", "description", "code", "number", "price")
_KIND_BY_FIELD = {
    "description": "description",
    "supplier_code": "code",
    "barcode": "code",
    "unit_cost_net": "price",
    "suggested_retail_price": "price",
    "unit_cost_net_converted": "price",
    "vat_rate": "number",
    "units_per_pack": "number",
    "fx_rate": "number",
    "source_row": "number",
}
_CONSTANT_NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)")
MIN_MATCHED = 2
MATCH_CONFIDENCE = 0.5


def default_kind(source: str) -> str:
    """The column type a source suggests; anything that is not a known field is text."""
    if source.startswith("field:"):
        return _KIND_BY_FIELD.get(source.removeprefix("field:"), "text")
    return "text"


def validate_kind(kind: str) -> str:
    if isinstance(kind, str) and kind in OUTPUT_KINDS:
        return kind
    raise ValueError(f"kind must be one of: {', '.join(OUTPUT_KINDS)}")


def parse_decimal_text(text: str) -> Decimal | None:
    """A plain decimal with `,` or `.` as separator; no thousands separators or exponents."""
    candidate = text.strip()
    if not _CONSTANT_NUMBER.fullmatch(candidate):
        return None
    return Decimal(candidate.replace(",", "."))


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
    kind: str | None = None  # None: legacy column, the value is written exactly as before


@dataclass(frozen=True)
class OutputFormat:
    name: str
    state: str
    columns: tuple[OutputColumn, ...]


@dataclass(frozen=True)
class OutputFit:
    matched: int
    total: int
    unmatched: tuple[str, ...]
    mismatch: bool


def check_fit(output_format: OutputFormat) -> OutputFit:
    """How many template columns the proposals recognise as product fields.

    A column matches when its proposal is a `field:*` source with enough confidence.
    Only a still-proposed template can mismatch: a confirmed one was already accepted.
    """
    unmatched = tuple(
        column.name for column in output_format.columns
        if not (column.proposal.source.startswith("field:") and column.proposal.confidence >= MATCH_CONFIDENCE)
    )
    total = len(output_format.columns)
    matched = total - len(unmatched)
    mismatch = output_format.state == "proposed" and matched < max(MIN_MATCHED, math.ceil(total / 2))
    return OutputFit(matched, total, unmatched, mismatch)


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
