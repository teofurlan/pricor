"""`ExportImport`: renders an approved import as files.

Only an approved session can be exported: the files are built from the frozen
`approved_result`, so they always match what the user approved.
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pricor.application.errors import InvalidInputError, InvalidOperationError
from pricor.domain.cells import display
from pricor.ports.exporter import Exporter, ImportExport, RejectedEntry
from pricor.ports.import_session import ImportSession
from pricor.ports.price_history import ImportedRecord

_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 40
_ID_CHARS = 8


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
    def __init__(self, get_session: Callable[[str], ImportSession], exporters: Sequence[Exporter]):
        self._get_session = get_session
        self._exporters = {exporter.format: exporter for exporter in exporters}

    def products(self, session_id: str, format: str) -> ExportedFile:
        exporter, session = self._resolve(session_id, format)
        return self._file(session, exporter, "products", exporter.export(self._view(session)))

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
