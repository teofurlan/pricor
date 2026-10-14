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


# -- agreement stage (heuristics + fine-tuned Laya) --


def paired(heuristics, laya):
    """Two aligned validation lists from (expected, predicted, score) triples."""
    return {
        "heuristics": [rec(e, p, s) for e, p, s in heuristics],
        "laya_finetuned": [rec(e, p, s) for e, p, s in laya],
    }


def test_agreement_is_calibrated_on_the_columns_where_both_classifiers_chose_the_same_role():
    from tools.benchmark.calibrate import calibrate_agreement

    # 25 agreed and right at 0.9; 5 agreed and wrong at 0.5; 10 disagreements that never count.
    heuristics = [("code", "code", 0.4)] * 25 + [("code", "ignore", 0.5)] * 5 + [("code", "code", 0.99)] * 10
    laya = [("code", "code", 0.9)] * 25 + [("code", "ignore", 0.5)] * 5 + [("code", "ignore", 0.99)] * 10

    agreement = calibrate_agreement(paired(heuristics, laya), 0.95, 20)

    assert (agreement.agreed, agreement.agreed_precision) == (30, 25 / 30)  # no minimum: below the target
    assert agreement.calibration.threshold == 0.9  # the higher of the two scores must reach it
    assert (agreement.calibration.support, agreement.calibration.precision) == (25, 1.0)
    assert agreement.calibration.total == 30


def test_agreement_is_not_enabled_when_no_setting_meets_the_target():
    from tools.benchmark.calibrate import calibrate_agreement

    wrong = [("code", "ignore", 0.9)] * 20 + [("code", "code", 0.9)] * 20

    agreement = calibrate_agreement(paired(wrong, wrong), 0.95, 20)

    assert agreement.calibration.threshold is None


def test_agreement_needs_both_classifiers_in_the_validation_answers():
    from tools.benchmark.calibrate import calibrate_agreement

    assert calibrate_agreement({"laya_finetuned": laya_records()}, 0.95, 20) is None


def test_the_document_records_the_agreement_stage_with_its_members_and_unconditional_precision():
    heuristics = [("code", "code", 0.4)] * 25 + [("code", "ignore", 0.5)] * 5
    laya = [("code", "code", 0.9)] * 25 + [("code", "ignore", 0.5)] * 5
    validation = {**paired(heuristics, laya), "gemma": [rec("code", "code", 0.9)] * 30}
    from tools.benchmark.calibrate import calibrate_agreement

    document = thresholds_document(
        calibrate_stages(validation, 0.95, 20), validation, "2026-10-14",
        calibrate_agreement(validation, 0.95, 20),
    )

    entry = document["stages"]["agreement"]
    assert entry["threshold"] == 0.9 and entry["members"] == ["heuristics", "laya"]
    assert (entry["agreed"], entry["agreed_precision"]) == (30, 25 / 30)
    assert (entry["support"], entry["precision"], entry["n"]) == (25, 1.0, 30)


def test_a_missing_agreement_leaves_the_document_without_that_stage():
    validation = {"laya_finetuned": laya_records()}

    document = thresholds_document(calibrate_stages(validation, 0.99, 10), validation, "2026-10-14")

    assert "agreement" not in document["stages"]
