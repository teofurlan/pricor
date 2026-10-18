"""Reads CSV, XLSX/XLSM and XLS files into rows of plain cells.

Safety: size and row limits are enforced, macros are never loaded (XLSX is
opened read-only with cached values, `keep_vba` off), nothing in a cell is
ever evaluated, and numeric cells become `Decimal(str(value))`, never float.
Percent-formatted numbers cross the boundary as percentage-point text (21%).
"""

import csv
import io
import math
import operator
import re
import zipfile
from collections.abc import Callable, Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
import xlrd

from pricor.ports.spreadsheet import (
    Cell,
    FileTooLargeError,
    Row,
    Sheet,
    SheetNotFoundError,
    SpreadsheetError,
    TooManyRowsError,
    UnsupportedFormatError,
)

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
# Excel's own row ceiling; bounds how many empty rows we buffer.
_MAX_PENDING_EMPTY = 1_048_576

_CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")  # utf-8-sig also reads plain utf-8
_CSV_DELIMITERS = (";", ",", "\t")
_SNIFF_LINES = 20
_XLSX_SUFFIXES = {".xlsx", ".xlsm"}
_OLE2_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_ENCRYPTED_MARKER = "EncryptedPackage".encode("utf-16le")
_ZIP_SIGNATURE = b"PK"


def _is_empty(row: Row) -> bool:
    return all(cell is None for cell in row)


def _decimal_from_float(value: float) -> Cell:
    """Shortest-repr Decimal; non-finite numbers carry no usable value."""
    if not math.isfinite(value):
        return None
    return Decimal(str(value))


def _text_cell(value: str) -> Cell:
    return value if value.strip() else None


_FORMAT_LITERALS = re.compile(r'"[^"]*"|\\.|_.|\*.')
_FORMAT_CONDITION = re.compile(
    r"\[(<=|>=|<>|=|<|>)([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\]"
)
_FORMAT_COMPARISONS = {
    "<": operator.lt, "<=": operator.le, "=": operator.eq,
    "<>": operator.ne, ">=": operator.ge, ">": operator.gt,
}


def _formatted_number(value: Cell, number_format: str) -> Cell:
    """Keep Excel percentage semantics without rounding to display precision.

    Only an active, unescaped percent token scales the stored fraction. Quoted
    literals, layout escapes and color/currency tags are not percent tokens.
    Format sections select positive/negative/zero values or explicit conditions.
    """
    if not isinstance(value, int | Decimal):
        return value
    sections = _FORMAT_LITERALS.sub("", number_format).split(";")[:3]
    conditions = [_FORMAT_CONDITION.search(section) for section in sections]
    if any(conditions):
        for section, condition in zip(sections, conditions, strict=True):
            if condition is None or _FORMAT_COMPARISONS[condition[1]](
                value, Decimal(condition[2])
            ):
                active = section
                break
        else:
            return value
    else:
        index = 2 if value == 0 and len(sections) > 2 else int(value < 0 and len(sections) > 1)
        active = sections[index]
    if "%" not in re.sub(r"\[[^\]]*\]", "", active):
        return value
    return f"{Decimal(value) * 100:f}%"


def _collect(rows: Iterable[Row], max_rows: int) -> tuple[Row, ...]:
    """Collect rows, dropping trailing empty rows and enforcing the row limit.

    Empty rows between content count towards the limit; trailing ones do not.
    """
    result: list[Row] = []
    pending: list[Row] = []
    for row in rows:
        if _is_empty(row):
            pending.append(row)
            if len(pending) > _MAX_PENDING_EMPTY:
                raise TooManyRowsError("too many consecutive empty rows")
            continue
        result.extend(pending)
        pending.clear()
        result.append(row)
        if len(result) > max_rows:
            raise TooManyRowsError(f"the sheet has more than {max_rows} rows")
    return tuple(result)


class FileSpreadsheetReader:
    def __init__(self, max_file_bytes: int = MAX_FILE_BYTES, max_rows: int = MAX_ROWS):
        self.max_file_bytes = max_file_bytes
        self.max_rows = max_rows

    # -- port --

    def sheet_names(self, path: Path) -> list[str]:
        kind = self._check(path)
        if kind == "csv":
            return [path.stem]
        if kind == "xlsx":
            workbook = self._open_xlsx(path)
            try:
                return [sheet.title for sheet in workbook.worksheets]
            finally:
                workbook.close()
        book = self._open_xls(path)
        try:
            return book.sheet_names()
        finally:
            book.release_resources()

    def read_sheet(self, path: Path, sheet: str | None = None) -> Sheet:
        kind = self._check(path)
        if kind == "csv":
            return self._read_csv(path, sheet)
        if kind == "xlsx":
            return self._read_xlsx(path, sheet)
        return self._read_xls(path, sheet)

    # -- validation --

    def _check(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            kind = "csv"
        elif suffix in _XLSX_SUFFIXES or suffix == ".xls":
            kind = "xlsx" if suffix in _XLSX_SUFFIXES else "xls"
        else:
            raise UnsupportedFormatError(
                f"unsupported file type {suffix or '(none)'!r}; "
                "expected .csv, .xlsx, .xlsm or .xls"
            )
        try:
            size = path.stat().st_size
        except OSError as error:
            raise SpreadsheetError(f"cannot read {path.name}: {error.strerror}") from error
        if size > self.max_file_bytes:
            raise FileTooLargeError(
                f"{path.name} is {size} bytes; the limit is {self.max_file_bytes}"
            )
        if kind != "csv":
            kind = self._sniff_binary_format(path, kind)
        return kind

    @staticmethod
    def _sniff_binary_format(path: Path, declared: str) -> str:
        """Trust the file signature over the extension (suppliers mislabel .xls as .xlsx)."""
        try:
            with path.open("rb") as handle:
                signature = handle.read(8)
        except OSError as error:
            raise SpreadsheetError(f"cannot read {path.name}: {error.strerror}") from error
        if signature.startswith(_OLE2_SIGNATURE):
            return "xls"
        if signature.startswith(_ZIP_SIGNATURE):
            return "xlsx"
        return declared  # let the format library report why it cannot read it

    @staticmethod
    def _pick(names: list[str], requested: str | None, has_content: Callable[[str], bool]) -> str:
        if requested is not None:
            if requested not in names:
                raise SheetNotFoundError(f"sheet {requested!r} not found; available: {names}")
            return requested
        for name in names:
            if has_content(name):
                return name
        raise SpreadsheetError("the file has no non-empty sheet")

    # -- CSV --

    def _read_csv(self, path: Path, sheet: str | None) -> Sheet:
        if sheet is not None and sheet != path.stem:
            raise SheetNotFoundError(f"sheet {sheet!r} not found; available: {[path.stem]}")
        text = self._decode(path.read_bytes())
        delimiter = self._sniff(text)
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        try:
            rows = _collect(
                (tuple(_text_cell(value) for value in record) for record in reader),
                self.max_rows,
            )
        except csv.Error as error:
            raise SpreadsheetError(f"cannot read {path.name}: {error}") from error
        if not rows:
            raise SpreadsheetError("the file has no non-empty sheet")
        return Sheet(path.stem, rows)

    @staticmethod
    def _decode(data: bytes) -> str:
        for encoding in _CSV_ENCODINGS:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise SpreadsheetError("cannot decode the file as text")  # unreachable: latin-1

    @staticmethod
    def _sniff(text: str) -> str:
        """Pick the delimiter whose field count is most regular over the first lines."""
        lines = [line for line in text.splitlines() if line.strip()][:_SNIFF_LINES]
        best, best_score = ",", 0.0
        for delimiter in _CSV_DELIMITERS:
            try:
                counts = [len(record) for record in csv.reader(lines, delimiter=delimiter)]
            except csv.Error:
                continue
            if not counts:
                continue
            modal = max(set(counts), key=counts.count)
            score = (modal - 1) * counts.count(modal) / len(counts)
            if score > best_score:
                best, best_score = delimiter, score
        return best

    # -- XLSX / XLSM --

    @staticmethod
    def _open_xlsx(path: Path):
        try:
            return openpyxl.load_workbook(path, read_only=True, data_only=True, keep_vba=False)
        except Exception as error:  # openpyxl surfaces many unrelated exception types
            raise SpreadsheetError(f"cannot read {path.name}: {error}") from error

    def _read_xlsx(self, path: Path, sheet: str | None) -> Sheet:
        workbook = self._open_xlsx(path)
        try:
            sheets = {worksheet.title: worksheet for worksheet in workbook.worksheets}
            cache: dict[str, tuple[Row, ...]] = {}

            def load(name: str) -> tuple[Row, ...]:
                if name not in cache:
                    worksheet = sheets[name]
                    worksheet.reset_dimensions()  # some writers declare a wrong used range
                    try:
                        cache[name] = _collect(
                            (
                                tuple(self._xlsx_cell(cell.value, cell.number_format) for cell in raw)
                                for raw in worksheet.iter_rows()
                            ),
                            self.max_rows,
                        )
                    except (zipfile.BadZipFile, ValueError, KeyError) as error:
                        raise SpreadsheetError(f"cannot read {path.name}: {error}") from error
                return cache[name]

            name = self._pick(list(sheets), sheet, lambda candidate: bool(load(candidate)))
            return Sheet(name, load(name))
        finally:
            workbook.close()

    @staticmethod
    def _xlsx_cell(value: Any, number_format: str = "General") -> Cell:
        if value is None:
            return None
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int | Decimal):
            return _formatted_number(value, number_format)
        if isinstance(value, float):
            return _formatted_number(_decimal_from_float(value), number_format)
        if isinstance(value, datetime | date):
            return value
        if isinstance(value, time | timedelta):
            return str(value)
        return _text_cell(str(value))

    # -- XLS --

    @staticmethod
    def _open_xls(path: Path):
        try:
            return xlrd.open_workbook(
                path, on_demand=True, formatting_info=True, logfile=io.StringIO()
            )
        except Exception as error:  # xlrd raises XLRDError, struct.error, OSError...
            if _ENCRYPTED_MARKER in path.read_bytes():
                raise SpreadsheetError(
                    f"{path.name} is encrypted (password-protected); remove the password first"
                ) from error
            raise SpreadsheetError(f"cannot read {path.name}: {error}") from error

    def _read_xls(self, path: Path, sheet: str | None) -> Sheet:
        book = self._open_xls(path)
        try:
            names = book.sheet_names()

            def load(name: str) -> tuple[Row, ...]:
                worksheet = book.sheet_by_name(name)
                return _collect(
                    (
                        tuple(self._xls_cell(book, cell) for cell in worksheet.row(index))
                        for index in range(worksheet.nrows)
                    ),
                    self.max_rows,
                )

            name = self._pick(names, sheet, lambda candidate: bool(load(candidate)))
            return Sheet(name, load(name))
        finally:
            book.release_resources()

    @staticmethod
    def _xls_cell(book, cell) -> Cell:
        kind, value = cell.ctype, cell.value
        if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
            return None
        if kind == xlrd.XL_CELL_TEXT:
            return _text_cell(value)
        if kind == xlrd.XL_CELL_BOOLEAN:
            return "TRUE" if value else "FALSE"
        if kind == xlrd.XL_CELL_ERROR:
            return xlrd.error_text_from_code.get(value, "#ERROR")
        if kind == xlrd.XL_CELL_DATE:
            try:
                return xlrd.xldate.xldate_as_datetime(value, book.datemode)
            except (xlrd.xldate.XLDateError, OverflowError, ValueError):
                return _decimal_from_float(value)
        # XLS stores every number as a float; integral values are plain integers.
        number = int(value) if float(value).is_integer() and abs(value) < 1e15 else _decimal_from_float(value)
        format_key = book.xf_list[cell.xf_index].format_key
        return _formatted_number(number, book.format_map[format_key].format_str)
