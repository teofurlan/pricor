"""Reference labels: one hand-assigned role per real column of the downloaded price lists.

The file holds headers and notes only, never cell values. The values are read from the raw
files (gitignored) when a dataset is built.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pricor.domain.roles import ColumnRole


class LabelError(ValueError):
    """The labels file is malformed."""


@dataclass(frozen=True)
class SheetSpec:
    source_id: str
    sheet: str
    header_row: int | None  # 0-based; None: the sheet has no header row


@dataclass(frozen=True)
class LabeledColumn:
    source_id: str
    sheet: str
    index: int
    header: str
    role: ColumnRole
    note: str | None = None


@dataclass(frozen=True)
class LabelSet:
    sheets: tuple[SheetSpec, ...]
    columns: tuple[LabeledColumn, ...]

    def header_row(self, source_id: str, sheet: str) -> int | None:
        for spec in self.sheets:
            if (spec.source_id, spec.sheet) == (source_id, sheet):
                return spec.header_row
        raise KeyError((source_id, sheet))

    def only(self, columns: tuple[LabeledColumn, ...]) -> "LabelSet":
        """The same sheet specs restricted to `columns`."""
        return LabelSet(self.sheets, columns)


def _sheet(item: dict) -> SheetSpec:
    header_row = item.get("header_row")
    if header_row is not None and (not isinstance(header_row, int) or header_row < 0):
        raise LabelError(f"bad header_row in {item!r}")
    try:
        source_id, sheet = item["source_id"], item["sheet"]
    except KeyError as error:
        raise LabelError(f"sheet entry without {error}") from None
    return SheetSpec(source_id, sheet, header_row)


def _column(item: dict, known: set[tuple[str, str]]) -> LabeledColumn:
    try:
        entry = LabeledColumn(
            item["source_id"],
            item["sheet"],
            item["index"],
            item["header"],
            ColumnRole(item["role"]),
            item.get("note"),
        )
    except (KeyError, ValueError) as error:
        raise LabelError(f"bad column entry {item!r}: {error}") from None
    if not isinstance(entry.index, int) or isinstance(entry.index, bool) or entry.index < 0:
        raise LabelError(f"bad column index in {item!r}")
    if not isinstance(entry.header, str):
        raise LabelError(f"header must be text in {item!r}")
    if (entry.source_id, entry.sheet) not in known:
        raise LabelError(f"{entry.source_id}/{entry.sheet} has no sheet entry")
    return entry


def load_labels(path: Path) -> LabelSet:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    sheets = tuple(_sheet(item) for item in document["sheets"])
    known = {(spec.source_id, spec.sheet) for spec in sheets}
    columns = tuple(_column(item, known) for item in document["columns"])
    keys = [(c.source_id, c.sheet, c.index) for c in columns]
    if len(set(keys)) != len(keys):
        raise LabelError("a column is labeled twice")
    return LabelSet(sheets, columns)
