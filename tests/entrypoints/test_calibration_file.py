import json

import pytest

from pricor.entrypoints.calibration_file import CalibrationFileError, load_calibration

DOCUMENT = {
    "calibrated_on": "2026-10-14",
    "method": "lowest validation confidence with precision >= 0.95 and support >= 20",
    "target_precision": 0.95,
    "stages": {
        "laya": {"threshold": 0.83, "n": 161, "support": 120, "precision": 0.97},
        "gemma": {"threshold": None, "n": 40, "reason": "no threshold meets the target"},
    },
}


def write(tmp_path, document):
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_calibrated_stage_gets_its_threshold_and_is_marked_calibrated(tmp_path):
    calibration = load_calibration(write(tmp_path, DOCUMENT))

    assert calibration.threshold_for("laya") == (0.83, True)


def test_a_stage_without_a_usable_threshold_keeps_the_placeholder_and_is_not_calibrated(tmp_path):
    calibration = load_calibration(write(tmp_path, DOCUMENT))

    assert calibration.threshold_for("gemma") == (0.75, False)
    assert calibration.threshold_for("heuristics") == (0.75, False)


def test_the_provenance_of_the_calibration_is_kept(tmp_path):
    calibration = load_calibration(write(tmp_path, DOCUMENT))

    assert calibration.calibrated_on == "2026-10-14"
    assert "precision >= 0.95" in calibration.method


@pytest.mark.parametrize(
    "document",
    [
        {**DOCUMENT, "stages": {"laya": {"threshold": 1.4, "n": 3}}},
        {**DOCUMENT, "stages": {"laya": {"threshold": "high", "n": 3}}},
        {**DOCUMENT, "stages": []},
        {"stages": {}},
    ],
)
def test_a_malformed_file_is_refused(tmp_path, document):
    with pytest.raises(CalibrationFileError):
        load_calibration(write(tmp_path, document))


def test_a_missing_file_means_no_calibration(tmp_path):
    calibration = load_calibration(tmp_path / "absent.json")

    assert calibration.threshold_for("laya") == (0.75, False)
    assert calibration.calibrated_on is None
