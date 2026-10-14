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
