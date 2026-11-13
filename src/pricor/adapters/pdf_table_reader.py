"""Reads the first table of a PDF as rows of text cells (pdfplumber).

Only ruled/aligned tables that pdfplumber detects count; the first table with at
least two columns, searching page by page, is the sheet. Nothing in the file is
executed and a PDF without such a table is a `SpreadsheetError`. File contents are
untrusted data.
"""

from pathlib import Path

import pdfplumber

from pricor.ports.spreadsheet import Row, Sheet, SpreadsheetError

MIN_COLUMNS = 2
# A template's headers sit near the start; scanning an untrusted long PDF page by page is slow.
MAX_PAGES = 20


def _cell(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


class PdfTableReader:
    def sheet_names(self, path: Path) -> list[str]:
        return [path.stem]

    def read_sheet(self, path: Path, sheet: str | None = None) -> Sheet:
        try:
            with pdfplumber.open(path, pages=range(1, MAX_PAGES + 1)) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        rows: tuple[Row, ...] = tuple(tuple(_cell(c) for c in row) for row in table)
                        if max((len(row) for row in rows), default=0) >= MIN_COLUMNS:
                            return Sheet(path.stem, rows)
        except SpreadsheetError:
            raise
        except Exception as error:  # a damaged or encrypted PDF can fail in many parser-specific ways
            raise SpreadsheetError(f"cannot read the PDF {path.name}") from error
        raise SpreadsheetError("the PDF has no table")
