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
    TemplateColumn,
    validate_source,
)
from pricor.ports.spreadsheet import SpreadsheetError, SpreadsheetReader


class ManageOutputFormat:
    def __init__(
        self,
        reader: SpreadsheetReader,
        store: OutputFormatStore,
        fallback: OutputFormatProposer,
        proposer: OutputFormatProposer | None = None,
    ):
        self._reader = reader
        self.store = store
        self._fallback = fallback
        self._proposer = proposer

    def get(self) -> OutputFormat:
        result = self.store.get()
        if result is None:
            raise OutputFormatNotFoundError("no output format has been uploaded")
        return result

    def upload(self, path: Path, sheet: str | None = None, *, name: str | None = None) -> OutputFormat:
        rows = self._reader.read_sheet(path, sheet).rows
        header_index = next((i for i, row in enumerate(rows) if any(not is_blank(c) for c in row)), None)
        if header_index is None:
            raise SpreadsheetError("the template has no non-empty row")
        # Spreadsheet readers may omit trailing blank header cells even when
        # following rows populate those columns. Keep that template width.
        width = max(len(row) for row in rows[header_index:])
        header = (*rows[header_index], *([None] * (width - len(rows[header_index]))))
        samples = rows[header_index + 1:header_index + 6]
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
            tuple(OutputColumn(c.index, c.name, c.samples, p) for c, p in zip(columns, proposals, strict=True)),
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
            columns=tuple(replace(column, source=source) for column, source in zip(proposed.columns, validated, strict=True)),
        )
        self.store.save(confirmed)
        return confirmed

    def delete(self) -> None:
        self.store.delete()
