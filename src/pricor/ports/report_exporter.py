"""Port for turning a price-change report into a file."""

from typing import Protocol

from pricor.domain.price_report import PriceReport


class ReportExporter(Protocol):
    media_type: str
    extension: str  # with the dot

    def export(self, report: PriceReport) -> bytes:
        """The report as a file; every section, in a fixed column order."""
        ...
