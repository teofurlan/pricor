import logging

import pytest

from pricor.adapters.laya_classifier import LayaColumnClassifier
from pricor.application.cascade import AgreementStage, ClassifierStage, Member
from pricor.entrypoints.wiring import (
    configure_logging,
    dependencies_from_env,
    preload_from_env,
    preload_warm_up,
)

from ..application.fakes import FakeClassifier


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes "])
def test_the_flag_accepts_one_true_and_yes(value):
    assert preload_from_env({"PRICOR_PRELOAD_MODELS": value}) is True


@pytest.mark.parametrize("env", [{}, {"PRICOR_PRELOAD_MODELS": ""}, {"PRICOR_PRELOAD_MODELS": "0"},
                                 {"PRICOR_PRELOAD_MODELS": "no"}])
def test_the_flag_defaults_off(env):
    assert preload_from_env(env) is False


def test_the_warm_up_loads_the_laya_agent_through_the_existing_classifier():
    loads = []
    laya = LayaColumnClassifier(loader=lambda: loads.append(1) or object())
    warm_up = preload_warm_up([ClassifierStage("gemma", FakeClassifier({})), ClassifierStage("laya", laya)])

    assert loads == []
    warm_up()
    warm_up()
    assert loads == [1]


def test_the_warm_up_is_found_inside_an_agreement_stage():
    laya = LayaColumnClassifier(loader=lambda: object())
    stage = AgreementStage("agreement", Member("heuristics", FakeClassifier({})), Member("laya", laya))

    assert preload_warm_up([stage]) == laya.warm_up


def test_there_is_nothing_to_warm_up_when_laya_is_skipped_or_absent():
    laya = LayaColumnClassifier(loader=lambda: object())

    assert preload_warm_up([ClassifierStage("laya", laya, skipped_reason="no model")]) is None
    assert preload_warm_up([ClassifierStage("gemma", FakeClassifier({}))]) is None


def test_the_environment_flag_enables_the_warm_up_only_when_laya_can_run(tmp_path):
    base = {"PRICOR_DB": str(tmp_path / "p.db"), "PRICOR_LAYA_MODEL": str(tmp_path / "absent")}

    assert dependencies_from_env(base).warm_up is None
    assert dependencies_from_env({**base, "PRICOR_PRELOAD_MODELS": "1"}).warm_up is None  # model missing


def test_pricor_info_logs_reach_the_console_once_configured():
    logger = logging.getLogger("pricor")
    saved = (logger.level, list(logger.handlers))
    try:
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

        configure_logging()
        configure_logging()

        assert logging.getLogger("pricor.application.cascade").isEnabledFor(logging.INFO)
        assert len(logger.handlers) == 1
    finally:
        logger.handlers[:] = saved[1]
        logger.setLevel(saved[0])
