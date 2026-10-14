"""Port for assigning a semantic role to each column of a profiled sheet.

Implementations (keyword heuristics, a small local model, a larger model) all
receive the same deterministic profile and return the same result type, so a
benchmark can compare them on identical inputs. Results carry per-label scores
and an optional latency for that purpose.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pricor.domain.profile import ColumnProfile, SheetProfile


class ColumnRole(StrEnum):
    """Closed set of roles a column can play in a supplier price list."""

    CODE = "code"
    DESCRIPTION = "description"
    COST_PRICE = "cost_price"
    RETAIL_PRICE = "retail_price"
    VAT_RATE = "vat_rate"
    UNITS_PER_PACK = "units_per_pack"
    BARCODE = "barcode"
    DISCOUNT = "discount"
    CURRENCY = "currency"
    IGNORE = "ignore"


@dataclass(frozen=True)
class ColumnClassification:
    """The role chosen for one column.

    `scores` holds one value in [0, 1] per `ColumnRole` when the implementation
    can provide them (a model that only names a label may leave it empty).
    `score` is the confidence of the chosen `role`; `latency_seconds` is
    filled in by implementations that measure it.
    """

    index: int
    header: str
    role: ColumnRole
    score: float
    rationale: str
    scores: Mapping[ColumnRole, float] = field(default_factory=dict)
    latency_seconds: float | None = None


class ColumnClassifier(Protocol):
    def classify_column(
        self, column: ColumnProfile, sheet: SheetProfile | None = None
    ) -> ColumnClassification:
        """Classify one column; `sheet` is optional context about its neighbours."""
        ...

    def classify_sheet(self, sheet: SheetProfile) -> list[ColumnClassification]:
        """Classify every column of the sheet, in column order."""
        ...
