"""`ColumnClassifier` backed by the fine-tuned Laya model, run locally.

The model reads the same state text training used (`laya_state`) and answers the closed role
question. `scores` carries Laya's per-role probabilities and `score` its calibrated confidence
for the chosen role. `laya` and `torch` belong to the optional `laya` extra, so they are only
imported when the model is first needed: importing this module, and therefore the base install,
never requires them. A missing extra or model surfaces as `ModelNotInstalledError`.
"""

import time
from collections.abc import Callable, Mapping
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol

from pricor.domain.profile import ColumnProfile, SheetProfile
from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassification
from pricor.ports.model_errors import ModelNotInstalledError, ModelSchemaError

from .laya_state import QUESTION_ID, QUESTIONS, state_for_column

DEFAULT_MODEL_PATH = Path("models/laya-pricor")
DEVICES = ("auto", "cpu", "cuda")
_ROLES = {role.value: role for role in ColumnRole}
_INSTALL_HINT = "install the optional extra with `uv sync --extra laya`"


class LayaAgent(Protocol):
    def system_one(self, state: str, questions: dict[str, dict]) -> dict[str, Any]: ...


def resolve_device(requested: str, cuda_available: Callable[[], bool]) -> str:
    """`auto` picks CUDA when it is available and CPU otherwise; `cpu` and `cuda` are forced."""
    if requested not in DEVICES:
        raise ValueError(f"PRICOR_LAYA_DEVICE must be one of: {', '.join(DEVICES)}")
    if requested == "auto":
        return "cuda" if cuda_available() else "cpu"
    return requested


def laya_unavailable_reason(
    model_path: Path, find_spec: Callable[[str], object | None] = find_spec
) -> str | None:
    """Why the Laya stage cannot run (the extra or the weights are missing), or None."""
    if find_spec("laya") is None or find_spec("torch") is None:
        return f"the 'laya' extra is not installed: {_INSTALL_HINT}"
    if not (Path(model_path) / "model.safetensors").is_file():
        return f"no fine-tuned model at {model_path}: train it with `python -m tools.laya.train`"
    return None


def load_laya_agent(model_path: Path, device: str = "auto") -> LayaAgent:
    """Load the fine-tuned checkpoint; the heavy imports happen here and nowhere else."""
    import laya
    import torch

    chosen = resolve_device(device, torch.cuda.is_available)
    agent = laya.load(str(model_path), device=chosen)
    agent.system_one("Column header: warm-up\nColumn type: text", QUESTIONS)
    return agent


class LayaColumnClassifier:
    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        device: str = "auto",
        loader: Callable[[], LayaAgent] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self._load = loader or (lambda: load_laya_agent(model_path, device))
        self._model_path = model_path
        self._clock = clock
        self._agent: LayaAgent | None = None

    def classify_column(
        self, column: ColumnProfile, sheet: SheetProfile | None = None
    ) -> ColumnClassification:
        agent = self._agent_ready()
        started = self._clock()
        reply = agent.system_one(state_for_column(column), QUESTIONS)
        latency = self._clock() - started
        role, confidence, scores = _read_answer(reply)
        return ColumnClassification(
            index=column.index,
            header=column.raw_header,
            role=role,
            score=confidence,
            rationale=f"laya: {role.value} ({confidence:.2f})",
            scores=scores,
            latency_seconds=latency,
        )

    def classify_sheet(self, sheet: SheetProfile) -> list[ColumnClassification]:
        return [self.classify_column(column, sheet) for column in sheet.columns]

    def _agent_ready(self) -> LayaAgent:
        if self._agent is None:
            try:
                self._agent = self._load()
            except (ImportError, FileNotFoundError, OSError) as error:
                raise ModelNotInstalledError(
                    f"the Laya model could not be loaded ({type(error).__name__}: {error}); "
                    f"{_INSTALL_HINT} and check {self._model_path}"
                ) from error
        return self._agent


def _read_answer(reply: Mapping[str, Any]) -> tuple[ColumnRole, float, dict[ColumnRole, float]]:
    try:
        answer = reply["answers"][QUESTION_ID]
        choice, confidence = answer["choice"], float(answer["confidence"])
        probabilities = answer["probabilities"]
        role = _ROLES[choice]
        scores = {_ROLES[label]: float(value) for label, value in probabilities.items()}
    except (KeyError, TypeError, ValueError) as error:
        raise ModelSchemaError(f"unexpected Laya answer ({type(error).__name__}: {error})") from error
    if not 0.0 <= confidence <= 1.0:
        raise ModelSchemaError(f"Laya confidence {confidence} is outside [0, 1]")
    return role, confidence, scores
