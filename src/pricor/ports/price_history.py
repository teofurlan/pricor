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
    ) -> None:
        """Store the accepted records of one import. An id can be stored only once."""
        ...

    def imports_for(self, supplier: str) -> tuple[ImportSummary, ...]:
        """The supplier's imports, oldest first."""
        ...

    def records_of(self, import_id: str) -> tuple[ImportedRecord, ...]:
        """Records in file order, or raise `ImportNotFoundError`."""
        ...
