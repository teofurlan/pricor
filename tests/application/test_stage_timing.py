import logging
import re

from pricor.application.cascade import ClassifierStage, run_cascade
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.model_errors import ModelNotInstalledError

from .fakes import FakeClassifier
from .fakes import FakeAdvisor
from .test_import_first_time import make, proposal, start

ROWS = [["Codigo", "Precio"], ["A-1", "10"], ["A-2", "20"]]
CONFIDENT = {"Codigo": (ColumnRole.CODE, 0.99), "Precio": (ColumnRole.COST_PRICE, 0.99)}


def timing_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]


def test_each_cascade_stage_that_ran_logs_its_name_and_seconds(caplog):
    stages = [
        ClassifierStage("laya", FakeClassifier({}), 0.5),  # settles nothing
        ClassifierStage("gemma", FakeClassifier(CONFIDENT)),
    ]
    with caplog.at_level(logging.INFO, logger="pricor"):
        run_cascade(stages, profile_sheet(ROWS))

    lines = timing_lines(caplog)
    assert [re.fullmatch(r"cascade stage (\w+): \d+\.\d{2}s", line) is not None for line in lines] == [True, True]
    assert [line.split(":")[0] for line in lines] == ["cascade stage laya", "cascade stage gemma"]


def test_a_skipped_stage_logs_no_timing(caplog):
    with caplog.at_level(logging.INFO, logger="pricor"):
        run_cascade([ClassifierStage("laya", FakeClassifier({}), skipped_reason="off")], profile_sheet(ROWS))

    assert timing_lines(caplog) == []


def test_a_stage_that_fails_still_logs_the_time_it_took(caplog):
    failing = FakeClassifier(error=ModelNotInstalledError("missing"))
    with caplog.at_level(logging.INFO, logger="pricor"):
        run_cascade([ClassifierStage("laya", failing)], profile_sheet(ROWS))

    assert [line.split(":")[0] for line in timing_lines(caplog)] == ["cascade stage laya"]


def test_the_plan_advisor_logs_its_seconds(caplog):
    use_case, _ = make(advisor=FakeAdvisor(proposal()))
    with caplog.at_level(logging.INFO, logger="pricor"):
        start(use_case)

    advisor_lines = [line for line in timing_lines(caplog) if line.startswith("plan advisor")]
    assert len(advisor_lines) == 1
    assert re.fullmatch(r"plan advisor: \d+\.\d{2}s", advisor_lines[0])
