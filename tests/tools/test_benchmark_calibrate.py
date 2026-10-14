import json

from tools.benchmark.calibrate import calibrate_stages, thresholds_document
from tools.benchmark.records import Record


def rec(expected, predicted, score, origin="real"):
    return Record(expected, predicted, score, None, origin, "src", "h", "s0")


def laya_records():
    right = [rec("code", "code", 0.90 + i / 1000) for i in range(30)]
    wrong_low = [rec("code", "ignore", 0.30 + i / 100) for i in range(5)]
    return right + wrong_low


def test_each_cascade_stage_is_calibrated_from_its_own_validation_answers():
    calibrations = calibrate_stages(
        {"laya_finetuned": laya_records(), "gemma": [rec("code", "code", 0.9)] * 3},
        target_precision=0.99,
        min_support=10,
    )

    assert set(calibrations) == {"laya", "gemma"}
    assert calibrations["laya"].threshold == 0.9
    assert calibrations["laya"].support == 30
    assert calibrations["gemma"].threshold is None  # three answers cannot meet a support of ten


def test_zero_shot_answers_are_not_a_cascade_stage():
    calibrations = calibrate_stages({"laya_zero_shot": laya_records()}, 0.99, 10)

    assert calibrations == {}


def test_the_document_is_loadable_and_records_how_the_thresholds_were_chosen(tmp_path):
    from pricor.entrypoints.calibration_file import load_calibration

    validation = {"laya_finetuned": laya_records()}
    calibrations = calibrate_stages(validation, 0.99, 10)

    document = thresholds_document(calibrations, validation, "2026-10-14")

    assert document["calibrated_on"] == "2026-10-14"
    assert "0.99" in document["method"] and "10" in document["method"]
    assert document["validation"] == {"n": 35, "real": 35, "synthetic": 0}
    assert document["stages"]["laya"]["n"] == 35
    assert document["stages"]["laya"]["real_only"] == {"support": 30, "precision": 1.0}
    path = tmp_path / "t.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_calibration(path).threshold_for("laya") == (0.9, True)


def test_an_unmet_target_is_written_as_a_null_threshold_with_its_reason():
    validation = {"gemma": [rec("code", "ignore", 0.9)] * 12}

    document = thresholds_document(calibrate_stages(validation, 0.95, 5), validation, "2026-10-14")

    assert document["stages"]["gemma"]["threshold"] is None
    assert "target" in document["stages"]["gemma"]["reason"]
