"""Port for reading the cells of a spreadsheet file.

Cell values are restricted to `str`, `Decimal`, `int`, `date`/`datetime` and
`None`. A `float` never crosses this boundary: adapters convert numeric cells
to `Decimal(str(value))` so prices keep their shortest exact representation.
File contents are untrusted data.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

Cell = str | Decimal | int | date | datetime | None
Row = tuple[Cell, ...]


class SpreadsheetError(Exception):
    """The file cannot be read. The message is safe to show to the user."""


class UnsupportedFormatError(SpreadsheetError):
    """The file extension is not one of the supported spreadsheet formats."""


class FileTooLargeError(SpreadsheetError):
    """The file is bigger than the configured size limit."""


class TooManyRowsError(SpreadsheetError):
    """The sheet has more rows than the configured limit."""


class SheetNotFoundError(SpreadsheetError):
    """The requested sheet does not exist in the workbook."""


@dataclass(frozen=True)
class Sheet:
    name: str
    rows: tuple[Row, ...]


class SpreadsheetReader(Protocol):
    def sheet_names(self, path: Path) -> list[str]:
        """Names of the sheets in the file (CSV files have a single one)."""
        ...

    def read_sheet(self, path: Path, sheet: str | None = None) -> Sheet:
        """Read one sheet; by default the first sheet that has any content."""
        ...
