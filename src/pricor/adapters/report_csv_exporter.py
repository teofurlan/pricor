"""CSV export of the price-change report.

Same file conventions as the product export (see `csv_exporter`): UTF-8 with a byte-order
mark, CRLF line ends, text neutralized against spreadsheet formulas, decimals in positional
notation. One row per product, tagged with its section; unchanged products are not listed.

`change_percent` is the display-rounded percentage (two decimals, half away from zero);
`change` and the costs keep the exact decimals. Costs are in each side's own currency and
are never converted.
"""

from collections.abc import Iterator

from pricor.adapters.export_common import csv_bytes
from pricor.domain.price_report import PriceChange, PriceReport, percent_text

REPORT_COLUMNS = (
    "section",
    "supplier_code",
    "description",
    "previous_currency",
    "current_currency",
    "previous_cost",
    "current_cost",
    "change",
    "change_percent",
    "anomaly",
    "note",
)


def _times(count: int) -> str:
    return f"{count} time" if count == 1 else f"{count} times"


def _change_row(section: str, item: PriceChange) -> list[object]:
    return [
        section,
        item.supplier_code,
        item.description,
        item.currency,
        item.currency,
        item.previous_cost,
        item.current_cost,
        item.change,
        None if item.change_ratio is None else percent_text(item.change_ratio),
        "yes" if item.anomaly else "no",
        None,
    ]


def _rows(report: PriceReport) -> Iterator[list[object]]:
    for item in report.increases:
        yield _change_row("increase", item)
    for item in report.decreases:
        yield _change_row("decrease", item)
    for item in report.from_zero:
        yield _change_row("from_zero", item)
    for product in report.new_products:
        yield [
            "new",
            product.supplier_code,
            product.description,
            None,
            product.currency,
            None,
            product.unit_cost_net,
            None,
            None,
            None,
            None,
        ]
    for product in report.discontinued:
        yield [
            "discontinued",
            product.supplier_code,
            product.description,
            product.currency,
            None,
            product.unit_cost_net,
            None,
            None,
            None,
            None,
            None,
        ]
    for moved in report.currency_changed:
        yield [
            "currency_changed",
            moved.supplier_code,
            moved.description,
            moved.previous_currency,
            moved.current_currency,
            moved.previous_cost,
            moved.current_cost,
            None,
            None,
            None,
            None,
        ]
    for code in report.ambiguous_codes:
        yield [
            "ambiguous",
            code.supplier_code,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            f"appears {_times(code.previous_count)} in the previous list "
            f"and {_times(code.current_count)} in the current list",
        ]


class ReportCsvExporter:
    format = "csv"
    media_type = "text/csv; charset=utf-8"
    extension = ".csv"

    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter

    def export(self, report: PriceReport) -> bytes:
        return csv_bytes(REPORT_COLUMNS, _rows(report), self.delimiter)
