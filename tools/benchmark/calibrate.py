"""Choose each cascade stage's confidence threshold from the validation answers only.

The held-out test set never reaches this module: it takes the validation records and nothing
else. Zero-shot Laya is benchmarked but is not a cascade stage, so it is not calibrated.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .metrics import Answer, Calibration, calibrate_threshold
from .records import Record

# Benchmark classifier name -> cascade stage name.
STAGE_OF = {"heuristics": "heuristics", "laya_finetuned": "laya", "gemma": "gemma"}


def _pairs(records: Sequence[Record]) -> list[tuple[float, bool]]:
    return [(record.score, record.predicted == record.expected and not record.failed) for record in records]


# The agreement stage settles a column when these two classifiers (benchmark names) choose the
# same role; its stage-level names are the ones the application shows.
AGREEMENT_MEMBERS = ("heuristics", "laya_finetuned")
AGREEMENT_STAGE = "agreement"


@dataclass(frozen=True)
class AgreementCalibration:
    """The agreement stage on a validation set.

    `agreed` and `agreed_precision` describe every column the two classifiers agreed on, with no
    confidence bar; `calibration` is the lowest bar (the higher of the two scores must reach it)
    whose accepted answers meet the target precision, or no threshold when none does.
    """

    agreed: int
    agreed_precision: float | None
    calibration: Calibration


def agreement_answers(first: Sequence[Answer], second: Sequence[Answer]) -> list[Answer]:
    """One answer per column for replaying the stage: agreed role with the higher score, else a
    score of -1 (below any confidence bar, so it never settles the column)."""
    return [
        Answer(a.role, max(a.score, b.score)) if a.role == b.role else Answer(a.role, -1.0)
        for a, b in zip(first, second, strict=True)
    ]


def calibrate_agreement(
    validation: Mapping[str, Sequence[Record]], target_precision: float, min_support: int
) -> AgreementCalibration | None:
    """Calibrate the agreement stage from the two members' validation answers (None if absent)."""
    first_name, second_name = AGREEMENT_MEMBERS
    if first_name not in validation or second_name not in validation:
        return None
    pairs = [
        (max(a.score, b.score), a.predicted == a.expected and not (a.failed or b.failed))
        for a, b in zip(validation[first_name], validation[second_name], strict=True)
        if a.predicted == b.predicted and not (a.failed or b.failed)
    ]
    correct = sum(ok for _, ok in pairs)
    return AgreementCalibration(
        len(pairs),
        correct / len(pairs) if pairs else None,
        calibrate_threshold(pairs, target_precision, min_support),
    )


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
    agreement: AgreementCalibration | None = None,
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
    if agreement is not None:
        stages[AGREEMENT_STAGE] = {
            "threshold": agreement.calibration.threshold,
            "members": ["heuristics", "laya"],
            "n": agreement.calibration.total,
            "agreed": agreement.agreed,
            "agreed_precision": agreement.agreed_precision,
            "support": agreement.calibration.support,
            "precision": agreement.calibration.precision,
            "reason": agreement.calibration.reason,
        }
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
