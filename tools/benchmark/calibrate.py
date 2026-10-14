"""Choose each cascade stage's confidence threshold from the validation answers only.

The held-out test set never reaches this module: it takes the validation records and nothing
else. Zero-shot Laya is benchmarked but is not a cascade stage, so it is not calibrated.
"""

from collections.abc import Mapping, Sequence

from .metrics import Calibration, calibrate_threshold
from .records import Record

# Benchmark classifier name -> cascade stage name.
STAGE_OF = {"heuristics": "heuristics", "laya_finetuned": "laya", "gemma": "gemma"}


def _pairs(records: Sequence[Record]) -> list[tuple[float, bool]]:
    return [(record.score, record.predicted == record.expected and not record.failed) for record in records]


def calibrate_stages(
    validation: Mapping[str, Sequence[Record]], target_precision: float, min_support: int
) -> dict[str, Calibration]:
    return {
        STAGE_OF[name]: calibrate_threshold(_pairs(records), target_precision, min_support)
        for name, records in validation.items()
        if name in STAGE_OF
    }


def thresholds_document(
    calibrations: Mapping[str, Calibration],
    validation: Mapping[str, Sequence[Record]],
    calibrated_on: str,
) -> dict:
    """The JSON the app reads, plus the provenance a reader needs to judge it."""
    by_stage = {STAGE_OF[name]: records for name, records in validation.items() if name in STAGE_OF}
    any_records = next(iter(by_stage.values()), [])
    first = next(iter(calibrations.values()), None)
    target = first.target_precision if first else 0.0
    support = first.min_support if first else 0
    stages = {}
    for stage, calibration in calibrations.items():
        entry = {
            "threshold": calibration.threshold,
            "n": calibration.total,
            "support": calibration.support,
            "precision": calibration.precision,
            "reason": calibration.reason,
        }
        if calibration.threshold is not None:
            real = [r for r in by_stage[stage] if r.origin == "real" and r.score >= calibration.threshold]
            correct = sum(r.predicted == r.expected and not r.failed for r in real)
            entry["real_only"] = {
                "support": len(real),
                "precision": correct / len(real) if real else None,
            }
        stages[stage] = entry
    return {
        "calibrated_on": calibrated_on,
        "method": (
            f"lowest validation confidence whose accepted answers (score >= threshold) have "
            f"precision >= {target:g} with support >= {support}"
        ),
        "target_precision": target,
        "min_support": support,
        "validation": {
            "n": len(any_records),
            "real": sum(r.origin == "real" for r in any_records),
            "synthetic": sum(r.origin == "synthetic" for r in any_records),
        },
        "stages": stages,
    }
