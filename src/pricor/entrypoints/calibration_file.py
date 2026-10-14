"""The calibrated cascade thresholds, read from a small committed JSON file.

`tools/benchmark` writes the file from a validation set (see `docs/benchmark.md`); the composition
root reads it. A stage with no usable threshold keeps the uncalibrated placeholder and the
session keeps saying so.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pricor.application.cascade import UNCALIBRATED_THRESHOLD

DEFAULT_CALIBRATION_PATH = Path(__file__).with_name("thresholds.json")


class CalibrationFileError(ValueError):
    """The thresholds file is malformed."""


@dataclass(frozen=True)
class Calibration:
    calibrated_on: str | None
    method: str | None
    thresholds: dict[str, float]
    # Stage order decided on the validation set, e.g. "laya>gemma"; None means the built-in order.
    cascade_order: str | None = None

    def threshold_for(self, stage: str) -> tuple[float, bool]:
        """The stage's threshold and whether it was calibrated (else the placeholder)."""
        if stage in self.thresholds:
            return self.thresholds[stage], True
        return UNCALIBRATED_THRESHOLD, False


def _threshold(stage: str, entry: object) -> float | None:
    if not isinstance(entry, dict) or "threshold" not in entry:
        raise CalibrationFileError(f"stage {stage!r} needs a 'threshold' entry")
    value = entry["threshold"]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
        raise CalibrationFileError(f"threshold of {stage!r} must be a number in [0, 1] or null")
    return float(value)


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> Calibration:
    """Read the thresholds; a missing file means nothing is calibrated."""
    path = Path(path)
    if not path.is_file():
        return Calibration(None, None, {})
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        stages = document["stages"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CalibrationFileError(f"unreadable thresholds file {path}: {error}") from error
    if not isinstance(stages, dict) or "calibrated_on" not in document:
        raise CalibrationFileError("the thresholds file needs 'calibrated_on' and a 'stages' object")
    thresholds = {}
    for stage, entry in stages.items():
        value = _threshold(stage, entry)
        if value is not None:
            thresholds[stage] = value
    order = document.get("cascade_order")
    if order is not None and (not isinstance(order, str) or not order):
        raise CalibrationFileError("cascade_order must be a non-empty text like 'laya>gemma'")
    return Calibration(document["calibrated_on"], document.get("method"), thresholds, order)
