"""Port for the accepted contract records of every approved import.

T15 compares two imports of one supplier by `supplier_code`, so the history
keeps one row per accepted record, keyed by import id, with money as exact
decimals.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pricor.domain.contract import ContractRecord
from pricor.domain.fx import FxSnapshot


class ImportNotFoundError(Exception):
    """No stored import has that id."""


class DuplicateImportError(Exception):
    """An import with that id is already stored."""


@dataclass(frozen=True)
class ImportedRecord:
    row_number: int  # 1-based row in the source file
    record: ContractRecord


@dataclass(frozen=True)
class ImportSummary:
    import_id: str
    supplier_key: str
    supplier_name: str
    imported_at: datetime
    record_count: int


class PriceHistory(Protocol):
    def record_import(
        self,
        import_id: str,
        supplier: str,
        imported_at: datetime,
        records: Sequence[ImportedRecord],
        fx: FxSnapshot | None = None,
    ) -> None:
        """Store the accepted records of one import, and the exchange-rate snapshot its run used.

        An id can be stored only once. Records keep the supplier's own values; converted
        values travel as optional extra fields of each record.
        """
        ...

    def imports_for(self, supplier: str) -> tuple[ImportSummary, ...]:
        """The supplier's imports, oldest first."""
        ...

    def records_of(self, import_id: str) -> tuple[ImportedRecord, ...]:
        """Records in file order, or raise `ImportNotFoundError`."""
        ...

    def fx_of(self, import_id: str) -> FxSnapshot | None:
        """The snapshot the import's run converted with, `None` if it converted nothing."""
        ...
