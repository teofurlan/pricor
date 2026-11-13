"""Read a template, propose its sources and activate only explicit confirmation."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from pricor.application.errors import InvalidInputError
from pricor.domain.cells import display, is_blank
from pricor.ports.model_errors import ModelError
from pricor.ports.output_format import (
    OutputColumn,
    OutputFormat,
    OutputFormatNotFoundError,
    OutputFormatProposer,
    OutputFormatStore,
    OutputProposal,
    TemplateColumn,
    default_kind,
    parse_decimal_text,
    validate_kind,
    validate_source,
)
from pricor.ports.spreadsheet import SpreadsheetError, SpreadsheetReader, UnsupportedFormatError

MAX_COLUMNS = 200
MAX_NAME_LENGTH = 100


class ManageOutputFormat:
    def __init__(
        self,
        reader: SpreadsheetReader,
        store: OutputFormatStore,
        fallback: OutputFormatProposer,
        proposer: OutputFormatProposer | None = None,
        pdf_reader: SpreadsheetReader | None = None,
    ):
        self._reader = reader
        self._pdf_reader = pdf_reader
        self.store = store
        self._fallback = fallback
        self._proposer = proposer

    def get(self) -> OutputFormat:
        result = self.store.get()
        if result is None:
            raise OutputFormatNotFoundError("no output format has been uploaded")
        return result

    def upload(self, path: Path, sheet: str | None = None, *, name: str | None = None) -> OutputFormat:
        if path.suffix.lower() == ".pdf":
            if self._pdf_reader is None:
                raise UnsupportedFormatError("PDF templates are not supported here")
            rows = self._pdf_reader.read_sheet(path, None).rows
        else:
            rows = self._reader.read_sheet(path, sheet).rows
        header_index = next((i for i, row in enumerate(rows) if any(not is_blank(c) for c in row)), None)
        if header_index is None:
            raise SpreadsheetError("the template has no non-empty row")
        samples = rows[header_index + 1:header_index + 6]
        # Spreadsheet readers may omit trailing blank header cells even when the
        # sample rows populate those columns. Keep that width, but only from the
        # header and its samples: a stray cell further down is not a column.
        width = max(len(row) for row in (rows[header_index], *samples))
        header = (*rows[header_index], *([None] * (width - len(rows[header_index]))))
        columns = tuple(
            TemplateColumn(
                index,
                f"Column {index + 1}" if is_blank(cell) else display(cell),
                tuple(display(row[index]) if index < len(row) and row[index] is not None else "" for row in samples),
            )
            for index, cell in enumerate(header)
        )
        try:
            proposals = self._proposer.propose(columns) if self._proposer else self._fallback.propose(columns)
        except ModelError:
            proposals = self._fallback.propose(columns)
        result = OutputFormat(
            name if name is not None else path.name,
            "proposed",
            tuple(OutputColumn(c.index, c.name, c.samples, p, kind=default_kind(p.source)) for c, p in zip(columns, proposals, strict=True)),
        )
        self.store.save(result)
        return result

    def confirm(self, sources: Sequence[str]) -> OutputFormat:
        proposed = self.get()
        if len(sources) != len(proposed.columns):
            raise InvalidInputError("provide exactly one source for every template column")
        try:
            validated = tuple(validate_source(source) for source in sources)
        except ValueError as error:
            raise InvalidInputError(str(error)) from error
        confirmed = replace(
            proposed,
            state="confirmed",
            columns=tuple(
                replace(column, source=source, kind=default_kind(source))
                for column, source in zip(proposed.columns, validated, strict=True)
            ),
        )
        self.store.save(confirmed)
        return confirmed

    def define(self, columns: Sequence[tuple]) -> OutputFormat:
        """Save the user's own column list, confirmed: exactly these columns, in this order.

        Each column is `(name, source, template_index[, kind])`. A template index links the
        column to a column of the stored template, keeping its samples and proposal. A
        missing kind defaults to the one the source suggests.
        """
        if not 1 <= len(columns) <= MAX_COLUMNS:
            raise InvalidInputError(f"provide at least one column and at most {MAX_COLUMNS}")
        stored = self.store.get()
        template = {column.index: column for column in stored.columns} if stored else {}
        seen: set[str] = set()
        result: list[OutputColumn] = []
        for position, (raw_name, source, template_index, *rest) in enumerate(columns):
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            if not 1 <= len(name) <= MAX_NAME_LENGTH:
                raise InvalidInputError(f"every column needs a name of 1 to {MAX_NAME_LENGTH} characters")
            if name.casefold() in seen:
                raise InvalidInputError(f"column names must be unique; {name!r} is repeated")
            seen.add(name.casefold())
            try:
                validated = validate_source(source)
            except ValueError as error:
                raise InvalidInputError(str(error)) from error
            raw_kind = rest[0] if rest else None
            try:
                kind = default_kind(validated) if raw_kind is None else validate_kind(raw_kind)
            except ValueError as error:
                raise InvalidInputError(str(error)) from error
            if (
                kind in ("number", "price")
                and validated.startswith("constant:")
                and parse_decimal_text(validated.removeprefix("constant:")) is None
            ):
                raise InvalidInputError(f"column {name!r}: a {kind} constant must be a number such as 12,50")
            if template_index is None:
                result.append(OutputColumn(position, name, (), OutputProposal(validated, "user", 1.0), validated, kind))
                continue
            linked = template.get(template_index)
            if linked is None:
                raise InvalidInputError(f"there is no template column {template_index}")
            result.append(OutputColumn(position, name, linked.samples, linked.proposal, validated, kind))
        linked_template = any(column[2] is not None for column in columns)
        defined = OutputFormat(stored.name if stored and linked_template else "", "confirmed", tuple(result))
        self.store.save(defined)
        return defined

    def delete(self) -> None:
        self.store.delete()
