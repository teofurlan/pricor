"""Port for turning an approved import into files a store can use.

Two artifacts per import: the products in the target contract (`export`) and
the rejected-rows report (`export_rejected`). Both are built from the same
`ImportExport` view, so a file can never disagree with what the user approved.
"""

from dataclasses import dataclass
from typing import Protocol

from pricor.ports.price_history import ImportedRecord

# Fixed order of the exported product columns: the target contract fields in
# declaration order, then traceability.
CONTRACT_COLUMNS = (
    "supplier_code",
    "description",
    "unit_cost_net",
    "currency",
    "vat_rate",
    "units_per_pack",
    "barcode",
    "suggested_retail_price",
)
# Written between the contract and traceability columns, only when some record was converted.
CONVERTED_COLUMNS = ("unit_cost_net_converted", "fx_rate", "fx_source", "fx_date")
TRACEABILITY_COLUMNS = ("source_row",)  # 1-based row number in the supplier's file
PRODUCT_COLUMNS = CONTRACT_COLUMNS + TRACEABILITY_COLUMNS

# Fixed leading columns of the rejected-rows report; the original cells follow.
REJECTED_COLUMNS = ("source_row", "reasons")


@dataclass(frozen=True)
class RejectedEntry:
    row_number: int
    cells: tuple[str, ...]  # the original cells, as text
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ImportExport:
    supplier_name: str
    accepted: tuple[ImportedRecord, ...]
    rejected: tuple[RejectedEntry, ...]
    source_headers: tuple[str, ...]  # names for the original cells in the rejected report


class Exporter(Protocol):
    format: str  # "csv", "xlsx": the value of the `format` request parameter
    media_type: str
    extension: str  # with the dot

    def export(self, data: ImportExport) -> bytes:
        """The products file."""
        ...

    def export_rejected(self, data: ImportExport) -> bytes:
        """The rejected-rows report."""
        ...
