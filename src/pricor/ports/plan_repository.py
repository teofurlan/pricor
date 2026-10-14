"""Port for keeping the approved plan of each supplier, version after version.

Plans are never overwritten: every approval adds a version, and `latest_for`
returns the newest. Each version carries the fingerprint of the sheet it was
approved against (what T14 compares when the supplier sends a new file).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pricor.domain.plan import ImportPlan


@dataclass(frozen=True)
class ColumnFingerprint:
    index: int
    header: str  # normalized: trimmed, whitespace collapsed, case-folded
    apparent_type: str  # `ColumnType` value


@dataclass(frozen=True)
class SheetFingerprint:
    sheet_name: str
    header_row: int | None
    columns: tuple[ColumnFingerprint, ...]


@dataclass(frozen=True)
class StoredPlan:
    supplier_key: str  # normalized supplier name: the identity of the supplier
    supplier_name: str  # the name as the user wrote it when this version was saved
    version: int  # 1 for the first approved plan of the supplier
    plan: ImportPlan
    fingerprint: SheetFingerprint
    created_at: datetime

    @property
    def contract_version(self) -> str:
        return self.plan.contract_version

    @property
    def engine_version(self) -> str:
        return self.plan.engine_version


class PlanRepository(Protocol):
    def save(
        self, supplier: str, plan: ImportPlan, fingerprint: SheetFingerprint, created_at: datetime
    ) -> StoredPlan:
        """Add a new version for the supplier and return it."""
        ...

    def latest_for(self, supplier: str) -> StoredPlan | None:
        """The newest version, or `None` if the supplier has no approved plan."""
        ...

    def versions_for(self, supplier: str) -> tuple[StoredPlan, ...]:
        """Every version, oldest first."""
        ...
