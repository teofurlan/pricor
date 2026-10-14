"""`ReportPriceChanges`: what changed between an approved import and the one before it.

The comparison is always against the supplier's previous *approved* import (the price
history only holds approved ones), never against another supplier's or a later one.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from pricor.application.errors import (
    InvalidInputError,
    InvalidOperationError,
    NoPreviousImportError,
)
from pricor.application.export_import import ExportedFile, slug
from pricor.domain.price_report import DEFAULT_ANOMALY_THRESHOLD, PriceReport, compare_price_lists
from pricor.ports.import_session import ImportSession
from pricor.ports.price_history import ImportSummary, PriceHistory
from pricor.ports.report_exporter import ReportExporter

_ID_CHARS = 8


@dataclass(frozen=True)
class ImportComparison:
    current: ImportSummary
    previous: ImportSummary
    report: PriceReport


def parse_threshold(text: str | None) -> Decimal:
    """A threshold as the ratio the user typed (`0.30` is 30%); `None` is the default."""
    if text is None:
        return DEFAULT_ANOMALY_THRESHOLD
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        value = None
    if value is None or not value.is_finite() or value < 0:
        raise InvalidInputError(
            f"threshold must be a ratio of zero or more such as 0.30 for 30%, got {text!r}"
        )
    return value


class ReportPriceChanges:
    def __init__(
        self,
        get_session: Callable[[str], ImportSession],
        history: PriceHistory,
        exporter: ReportExporter | None = None,
    ):
        self._get_session = get_session
        self._history = history
        self._exporter = exporter

    def compare(
        self, session_id: str, threshold: Decimal = DEFAULT_ANOMALY_THRESHOLD
    ) -> ImportComparison:
        session = self._get_session(session_id)
        if not session.approved:
            raise InvalidOperationError(
                f"the session is {session.status.value}; approve it before asking what changed"
            )
        imports = self._history.imports_for(session.supplier_name)
        position = next(
            (index for index, item in enumerate(imports) if item.import_id == session.id), None
        )
        if position is None:
            raise InvalidOperationError("this import is not in the price history")
        if position == 0:
            raise NoPreviousImportError(
                f"{session.supplier_name} has no earlier approved import to compare with"
            )
        previous, current = imports[position - 1], imports[position]
        report = compare_price_lists(
            [item.record for item in self._history.records_of(previous.import_id)],
            [item.record for item in self._history.records_of(current.import_id)],
            threshold,
        )
        return ImportComparison(current, previous, report)

    def export(
        self, session_id: str, threshold: Decimal = DEFAULT_ANOMALY_THRESHOLD
    ) -> ExportedFile:
        if self._exporter is None:
            raise InvalidOperationError("no report exporter is available")
        comparison = self.compare(session_id, threshold)
        name = (
            f"pricor-{slug(comparison.current.supplier_name)}-"
            f"{session_id[:_ID_CHARS]}-price-changes{self._exporter.extension}"
        )
        return ExportedFile(name, self._exporter.media_type, self._exporter.export(comparison.report))
