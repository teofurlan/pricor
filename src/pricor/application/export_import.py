"""`ExportImport`: renders an approved import as files.

Only an approved session can be exported: the files are built from the frozen
`approved_result` and the products layout in force at approval, so they always
match what the user approved.
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from pricor.application.errors import InvalidInputError, InvalidOperationError
from pricor.domain.cells import display
from pricor.ports.exporter import Exporter, ImportExport, RejectedEntry
from pricor.ports.import_session import ImportSession
from pricor.ports.output_format import OutputFormat, OutputFormatExporter, OutputFormatStore
from pricor.ports.price_history import ImportedRecord

_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 40
_ID_CHARS = 8
MAX_COMBINED = 50


def _signature(layout: OutputFormat | None) -> tuple[tuple[str, str | None, str | None], ...] | None:
    if layout is None:
        return None
    return tuple((column.name, column.source, column.kind) for column in layout.columns)


@dataclass(frozen=True)
class ExportedFile:
    filename: str
    media_type: str
    content: bytes


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _SLUG_CHARS.sub("-", ascii_text.lower()).strip("-")[:_SLUG_MAX].strip("-") or "supplier"


def _text(cell: object) -> str:
    return "" if cell is None else display(cell)


class ExportImport:
    def __init__(
        self, get_session: Callable[[str], ImportSession], exporters: Sequence[Exporter],
        output_format: OutputFormatStore | None = None,
    ):
        self._get_session = get_session
        self._exporters = {exporter.format: exporter for exporter in exporters}
        self._output_format = output_format

    def _layout(self, session: ImportSession) -> OutputFormat | None:
        """The confirmed products layout of an approved session, `None` for the standard columns."""
        if session.output_format_frozen:
            output_format = session.approved_output_format
        else:  # approved before layouts were frozen: the store-wide layout, as before
            output_format = self._output_format.get() if self._output_format else None
        return output_format if output_format is not None and output_format.state == "confirmed" else None

    def products(self, session_id: str, format: str) -> ExportedFile:
        exporter, session = self._resolve(session_id, format)
        output_format = self._layout(session)
        view = self._view(session)
        if output_format is not None:
            content = cast(OutputFormatExporter, exporter).export_formatted(view, output_format)
        else:
            content = exporter.export(view)
        return self._file(session, exporter, "products", content)

    def combined(self, session_ids: Sequence[str], format: str, kind: str = "products") -> ExportedFile:
        """One file with the rows of several approved imports, in the order given."""
        if kind not in ("products", "rejected"):
            raise InvalidInputError(f"unknown kind {kind!r}; use products or rejected")
        if not 1 <= len(session_ids) <= MAX_COMBINED:
            raise InvalidInputError(f"combine between 1 and {MAX_COMBINED} imports")
        if len(set(session_ids)) != len(session_ids):
            raise InvalidInputError("each import can be combined only once")
        resolved = [self._resolve(session_id, format) for session_id in session_ids]
        exporter = cast(OutputFormatExporter, resolved[0][0])
        sessions = [session for _, session in resolved]
        views = [self._view(session) for session in sessions]
        if kind == "rejected":
            content = exporter.export_rejected_combined(views)
        else:
            layouts = [self._layout(session) for session in sessions]
            if any(_signature(layout) != _signature(layouts[0]) for layout in layouts):
                raise InvalidOperationError(
                    "these files were approved with different output formats; "
                    "export them separately or approve them again with the same format"
                )
            content = exporter.export_combined(views, layouts[0])
        name = f"pricor-combined-{len(sessions)}-files-{kind}{resolved[0][0].extension}"
        return ExportedFile(name, resolved[0][0].media_type, content)

    def rejected(self, session_id: str, format: str) -> ExportedFile:
        exporter, session = self._resolve(session_id, format)
        content = exporter.export_rejected(self._view(session))
        return self._file(session, exporter, "rejected", content)

    # -- internals ---------------------------------------------------------------

    def _resolve(self, session_id: str, format: str) -> tuple[Exporter, ImportSession]:
        exporter = self._exporters.get(format)
        if exporter is None:
            raise InvalidInputError(f"unknown format {format!r}; use one of: {', '.join(sorted(self._exporters))}")
        session = self._get_session(session_id)
        if not session.approved or session.approved_result is None:
            raise InvalidOperationError(
                f"the session is {session.status.value}; approve it before exporting"
            )
        return exporter, session

    @staticmethod
    def _file(session: ImportSession, exporter: Exporter, kind: str, content: bytes) -> ExportedFile:
        name = f"pricor-{slug(session.supplier_name)}-{session.id[:_ID_CHARS]}-{kind}{exporter.extension}"
        return ExportedFile(name, exporter.media_type, content)

    @staticmethod
    def _view(session: ImportSession) -> ImportExport:
        result = session.approved_result
        return ImportExport(
            session.supplier_name,
            tuple(
                ImportedRecord(item.row_number, item.record)
                for item in sorted(result.accepted, key=lambda row: row.row_number)
            ),
            tuple(
                RejectedEntry(item.row_number, tuple(_text(c) for c in item.cells), item.reasons)
                for item in sorted(result.rejected, key=lambda row: row.row_number)
            ),
            tuple(column.plan_header for column in session.profile.columns),
        )
