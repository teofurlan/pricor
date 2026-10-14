from pathlib import Path

import pytest

from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.laya_classifier import DEFAULT_MODEL_PATH, LayaColumnClassifier
from pricor.entrypoints.wiring import build_stages, dependencies_from_env, laya_settings_from_env


class FakeClient:
    pass


def stages(env, unavailable=None):
    return build_stages(env, FakeClient(), laya_unavailable_reason=lambda path: unavailable)


def test_laya_leads_the_cascade_before_gemma_when_it_is_available():
    built = stages({})

    assert [stage.name for stage in built] == ["laya", "gemma"]
    assert isinstance(built[0].classifier, LayaColumnClassifier)
    assert built[0].skipped_reason is None


def test_heuristics_take_over_as_the_fallback_when_laya_is_unavailable():
    built = stages({}, unavailable="the 'laya' extra is not installed")

    assert [stage.name for stage in built] == ["laya", "heuristics", "gemma"]
    assert built[0].skipped_reason == "the 'laya' extra is not installed"
    assert built[1].skipped_reason is None
    assert isinstance(built[1].classifier, HeuristicColumnClassifier)


def test_the_model_path_and_device_come_from_the_environment():
    assert laya_settings_from_env({}) == (DEFAULT_MODEL_PATH, "auto")
    assert laya_settings_from_env({"PRICOR_LAYA_MODEL": "elsewhere", "PRICOR_LAYA_DEVICE": "cpu"}) == (
        Path("elsewhere"),
        "cpu",
    )


def test_an_unknown_laya_device_stops_the_startup():
    with pytest.raises(ValueError, match="PRICOR_LAYA_DEVICE"):
        laya_settings_from_env({"PRICOR_LAYA_DEVICE": "tpu"})


def test_a_missing_model_does_not_stop_the_app_and_is_reported_when_classifying(tmp_path):
    env = {"PRICOR_DB": str(tmp_path / "p.db"), "PRICOR_LAYA_MODEL": str(tmp_path / "absent")}

    use_case = dependencies_from_env(env).use_case

    laya_stage = use_case._stages[0]
    assert laya_stage.name == "laya"
    assert laya_stage.skipped_reason is not None
    assert "absent" in laya_stage.skipped_reason or "extra" in laya_stage.skipped_reason


def test_stage_thresholds_come_from_the_calibration_file_and_say_so(tmp_path):
    import json

    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "calibrated_on": "2026-10-14",
                "stages": {"laya": {"threshold": 0.62}, "gemma": {"threshold": None}},
            }
        ),
        encoding="utf-8",
    )

    laya, gemma = stages({"PRICOR_CALIBRATION": str(path)})

    assert (laya.threshold, laya.threshold_calibrated) == (0.62, True)
    assert (gemma.threshold, gemma.threshold_calibrated) == (0.75, False)


def test_the_committed_calibration_is_valid_and_covers_the_default_cascade():
    laya, gemma = stages({})

    assert laya.threshold_calibrated and gemma.threshold_calibrated


def calibration_file(tmp_path, order, agreement_threshold=0.97):
    import json

    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "calibrated_on": "2026-10-14",
                "cascade_order": order,
                "stages": {
                    "laya": {"threshold": 0.9},
                    "gemma": {"threshold": 0.8},
                    "agreement": {"threshold": agreement_threshold},
                },
            }
        ),
        encoding="utf-8",
    )
    return {"PRICOR_CALIBRATION": str(path)}


def test_an_agreement_stage_leads_the_cascade_when_the_calibrated_order_says_so(tmp_path):
    from pricor.application.cascade import AgreementStage

    built = stages(calibration_file(tmp_path, "agreement>laya>gemma"))

    assert [stage.name for stage in built] == ["agreement", "laya", "gemma"]
    agreement = built[0]
    assert isinstance(agreement, AgreementStage)
    assert (agreement.first.name, agreement.second.name) == ("heuristics", "laya")
    assert isinstance(agreement.first.classifier, HeuristicColumnClassifier)
    assert isinstance(agreement.second.classifier, LayaColumnClassifier)
    assert (agreement.min_confidence, agreement.min_confidence_calibrated) == (0.97, True)
    assert agreement.skipped_reason is None


def test_the_agreement_stage_is_skipped_with_the_reason_when_laya_is_unavailable(tmp_path):
    built = stages(calibration_file(tmp_path, "agreement>laya>gemma"), unavailable="no model")

    assert [stage.name for stage in built] == ["agreement", "laya", "heuristics", "gemma"]
    assert built[0].skipped_reason == "no model"


def test_an_agreement_stage_without_a_calibrated_threshold_is_not_enabled(tmp_path):
    env = calibration_file(tmp_path, "agreement>laya>gemma", agreement_threshold=None)

    assert [stage.name for stage in stages(env)] == ["laya", "gemma"]


def test_an_order_naming_an_unknown_stage_stops_the_startup(tmp_path):
    with pytest.raises(ValueError, match="oracle"):
        stages(calibration_file(tmp_path, "oracle>gemma"))


def test_the_committed_calibration_decides_the_shipped_order():
    from pricor.entrypoints.calibration_file import load_calibration

    order = load_calibration().cascade_order

    assert order is not None
    assert [stage.name for stage in stages({})] == order.split(">")
