"""One classifier answer about one labeled column, as stored in the raw benchmark JSON."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Record:
    expected: str
    predicted: str
    score: float
    latency_seconds: float | None  # per column; for a sheet-level model, the call that served it
    origin: str  # "real" or "synthetic"
    source: str
    header: str
    sheet: str  # which model call (or sheet) this column belonged to
    failed: bool = False  # the model gave no valid answer; `predicted` is a placeholder

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Record":
        return cls(**data)
