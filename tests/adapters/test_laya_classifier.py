import subprocess
import sys

import pytest

from pricor.adapters.laya_classifier import (
    LayaColumnClassifier,
    laya_unavailable_reason,
    resolve_device,
)
from pricor.adapters.laya_state import QUESTION_ID, QUESTIONS, state_for_column
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.model_errors import ModelNotInstalledError, ModelSchemaError

ROWS = [
    ["Código", "Precio"],
    ["A-1", "1.234,50"],
    ["A-2", "980,00"],
    ["A-3", "310,75"],
]


def answer(choice, confidence, probabilities=None):
    return {
        "answers": {
            QUESTION_ID: {
                "choice": choice,
                "confidence": confidence,
                "probabilities": probabilities or {choice: 0.9, "ignore": 0.1},
            }
        }
    }


class FakeAgent:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        return self.replies.pop(0)


class SteppingClock:
    """Each reading advances by 0.02 s, so one measured call (two readings) lasts 0.02 s."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.02
        return self.now


def classifier(agent, **options):
    return LayaColumnClassifier(loader=lambda: agent, **options)


def test_a_column_gets_the_role_confidence_and_per_role_scores_of_the_model():
    sheet = profile_sheet(ROWS)
    agent = FakeAgent([answer("code", 0.93, {"code": 0.91, "cost_price": 0.05, "ignore": 0.04})])

    result = classifier(agent).classify_column(sheet.columns[0], sheet)

    assert result.index == 0
    assert result.header == "Código"
    assert result.role is ColumnRole.CODE
    assert result.score == 0.93
    assert result.scores == {ColumnRole.CODE: 0.91, ColumnRole.COST_PRICE: 0.05, ColumnRole.IGNORE: 0.04}


def test_the_model_reads_the_shared_state_text_and_questions():
    sheet = profile_sheet(ROWS)
    agent = FakeAgent([answer("code", 0.9)])

    classifier(agent).classify_column(sheet.columns[0])

    assert agent.calls == [(state_for_column(sheet.columns[0]), QUESTIONS)]


def test_a_sheet_is_classified_column_by_column_in_order():
    sheet = profile_sheet(ROWS)
    agent = FakeAgent([answer("code", 0.9), answer("cost_price", 0.8)])

    results = classifier(agent).classify_sheet(sheet)

    assert [(r.index, r.role, r.score) for r in results] == [
        (0, ColumnRole.CODE, 0.9),
        (1, ColumnRole.COST_PRICE, 0.8),
    ]


def test_latency_of_each_model_call_is_recorded():
    sheet = profile_sheet(ROWS)
    agent = FakeAgent([answer("code", 0.9), answer("cost_price", 0.8)])

    results = classifier(agent, clock=SteppingClock()).classify_sheet(sheet)

    assert [round(r.latency_seconds, 3) for r in results] == [0.02, 0.02]


def test_the_model_is_loaded_lazily_and_only_once():
    loads = []

    def loader():
        loads.append(1)
        return FakeAgent([answer("code", 0.9), answer("code", 0.8)])

    sheet = profile_sheet(ROWS)
    laya = LayaColumnClassifier(loader=loader)
    assert loads == []

    laya.classify_column(sheet.columns[0])
    laya.classify_column(sheet.columns[1])

    assert loads == [1]


@pytest.mark.parametrize("error", [ImportError("No module named 'laya'"), FileNotFoundError("no model")])
def test_a_model_that_cannot_be_loaded_is_reported_as_not_installed(error):
    def loader():
        raise error

    sheet = profile_sheet(ROWS)

    with pytest.raises(ModelNotInstalledError, match="laya"):
        LayaColumnClassifier(loader=loader).classify_column(sheet.columns[0])


def test_an_answer_outside_the_closed_roles_is_rejected():
    sheet = profile_sheet(ROWS)

    with pytest.raises(ModelSchemaError):
        classifier(FakeAgent([answer("shipping", 0.9)])).classify_column(sheet.columns[0])


def test_unknown_probability_labels_are_rejected_not_dropped():
    sheet = profile_sheet(ROWS)

    with pytest.raises(ModelSchemaError):
        classifier(FakeAgent([answer("code", 0.9, {"code": 0.9, "bogus": 0.1})])).classify_column(
            sheet.columns[0]
        )


@pytest.mark.parametrize(
    ("requested", "cuda", "expected"),
    [("auto", True, "cuda"), ("auto", False, "cpu"), ("cpu", True, "cpu"), ("cuda", True, "cuda")],
)
def test_the_device_is_chosen_automatically_unless_forced(requested, cuda, expected):
    assert resolve_device(requested, cuda_available=lambda: cuda) == expected


def test_an_unknown_device_is_refused():
    with pytest.raises(ValueError, match="PRICOR_LAYA_DEVICE"):
        resolve_device("tpu", cuda_available=lambda: False)


def test_the_stage_is_unavailable_when_the_extra_is_missing(tmp_path):
    reason = laya_unavailable_reason(tmp_path, find_spec=lambda name: None)

    assert reason is not None
    assert "--extra laya" in reason


def test_the_stage_is_unavailable_when_the_model_is_missing(tmp_path):
    reason = laya_unavailable_reason(tmp_path / "absent", find_spec=lambda name: object())

    assert reason is not None
    assert "absent" in reason


def test_the_stage_is_available_with_the_extra_and_the_weights(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"x")

    assert laya_unavailable_reason(tmp_path, find_spec=lambda name: object()) is None


def test_importing_the_adapter_does_not_import_laya_or_torch():
    code = (
        "import sys, pricor.adapters.laya_classifier;"
        "assert 'laya' not in sys.modules and 'torch' not in sys.modules"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr
