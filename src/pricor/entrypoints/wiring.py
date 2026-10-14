"""Composition root: wires real adapters into the API.

Environment variables:

    PRICOR_OLLAMA_URL      base URL of the Ollama server   (default http://localhost:11434)
    PRICOR_OLLAMA_MODEL    model name                      (default gemma4:e4b)
    PRICOR_OLLAMA_TIMEOUT  seconds per model call          (default 180)
    PRICOR_DB              path of the SQLite file          (default: see `database_path_from_env`)
    PRICOR_LAYA_MODEL      folder of the fine-tuned Laya model (default models/laya-pricor)
    PRICOR_LAYA_DEVICE     auto | cpu | cuda               (default auto: CUDA when available)
    PRICOR_CALIBRATION     thresholds file (default: the calibrated one shipped in this package)
    PRICOR_FX_RATE_TYPE    rate type suggested for currency conversion (default oficial)
    PRICOR_FX_TIMEOUT      seconds per DolarAPI request      (default 10)

Run with: uv run uvicorn pricor.entrypoints.wiring:app_from_env --factory
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI

from pricor.adapters.dolarapi_provider import DEFAULT_TIMEOUT_SECONDS as FX_TIMEOUT
from pricor.adapters.dolarapi_provider import DolarApiProvider
from pricor.adapters.gemma_advisor import GemmaPlanAdvisor
from pricor.adapters.gemma_classifier import GemmaColumnClassifier
from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.ollama_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    OllamaClient,
)
from pricor.adapters.laya_classifier import (
    DEFAULT_MODEL_PATH,
    DEVICES,
    LayaColumnClassifier,
    laya_unavailable_reason,
)
from pricor.adapters.report_csv_exporter import ReportCsvExporter
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import AgreementStage, ClassifierStage, Member, Stage
from pricor.application.report_price_changes import ReportPriceChanges
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.entrypoints.calibration_file import DEFAULT_CALIBRATION_PATH, load_calibration
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.domain.fx import MARKET_RATE_TYPES
from pricor.entrypoints.web_app import DEFAULT_WEB_DIST


def ollama_client_from_env(env: Mapping[str, str]) -> OllamaClient:
    try:
        timeout = float(env.get("PRICOR_OLLAMA_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError as error:
        raise ValueError("PRICOR_OLLAMA_TIMEOUT must be a number of seconds") from error
    return OllamaClient(
        base_url=env.get("PRICOR_OLLAMA_URL", DEFAULT_BASE_URL),
        model=env.get("PRICOR_OLLAMA_MODEL", DEFAULT_MODEL),
        timeout=timeout,
    )


def laya_settings_from_env(env: Mapping[str, str]) -> tuple[Path, str]:
    """Where the fine-tuned Laya model lives and the device it runs on."""
    device = env.get("PRICOR_LAYA_DEVICE", "auto")
    if device not in DEVICES:
        raise ValueError(f"PRICOR_LAYA_DEVICE must be one of: {', '.join(DEVICES)}")
    return Path(env.get("PRICOR_LAYA_MODEL") or DEFAULT_MODEL_PATH), device


DEFAULT_ORDER = "laya>gemma"
STAGE_NAMES = ("agreement", "laya", "heuristics", "gemma")


def build_stages(
    env: Mapping[str, str],
    client: OllamaClient,
    laya_unavailable_reason: Callable[[Path], str | None] = laya_unavailable_reason,
) -> list[Stage]:
    """The classification cascade in the order the calibration file decided, then the user.

    The shipped order lives in `thresholds.json` (`cascade_order`, chosen on the validation set);
    without one it is Laya, then Gemma. When the `laya` extra or the fine-tuned model is missing
    the Laya stage is kept but marked skipped (the session shows why), and the keyword heuristics
    take its place as the first local stage so the app still proposes roles. An `agreement` stage
    (heuristics and Laya must pick the same role) is only built when it has a calibrated
    threshold.
    """
    model_path, device = laya_settings_from_env(env)
    reason = laya_unavailable_reason(model_path)
    calibration = load_calibration(Path(env.get("PRICOR_CALIBRATION") or DEFAULT_CALIBRATION_PATH))
    order = (calibration.cascade_order or DEFAULT_ORDER).split(">")
    unknown = [name for name in order if name not in STAGE_NAMES]
    if unknown:
        raise ValueError(f"cascade_order names unknown stages {unknown}; known: {', '.join(STAGE_NAMES)}")

    laya = LayaColumnClassifier(model_path, device)
    heuristics = HeuristicColumnClassifier()

    def classifier_stage(name: str, classifier, skipped_reason: str | None = None) -> ClassifierStage:
        threshold, calibrated = calibration.threshold_for(name)
        return ClassifierStage(name, classifier, threshold, calibrated, skipped_reason)

    stages: list[Stage] = []
    for name in order:
        if name == "agreement":
            threshold, calibrated = calibration.threshold_for(name)
            if calibrated:
                stages.append(
                    AgreementStage(
                        name, Member("heuristics", heuristics), Member("laya", laya), threshold, True, reason
                    )
                )
        elif name == "laya":
            stages.append(classifier_stage(name, laya, reason))
            if reason is not None and "heuristics" not in order:
                stages.append(classifier_stage("heuristics", heuristics))
        elif name == "heuristics":
            stages.append(classifier_stage(name, heuristics))
        else:
            stages.append(classifier_stage(name, GemmaColumnClassifier(client)))
    return stages


def fx_settings_from_env(env: Mapping[str, str]) -> tuple[str, float]:
    """The suggested rate type and the DolarAPI timeout; bad values stop the startup."""
    rate_type = env.get("PRICOR_FX_RATE_TYPE", "oficial")
    if rate_type not in MARKET_RATE_TYPES:
        raise ValueError(
            f"PRICOR_FX_RATE_TYPE must be one of: {', '.join(MARKET_RATE_TYPES)}"
        )
    try:
        timeout = float(env.get("PRICOR_FX_TIMEOUT", FX_TIMEOUT))
    except ValueError as error:
        raise ValueError("PRICOR_FX_TIMEOUT must be a number of seconds") from error
    return rate_type, timeout


def database_path_from_env(env: Mapping[str, str]) -> Path:
    """Where the SQLite file lives.

    `PRICOR_DB` wins. Otherwise a per-user data directory: `%LOCALAPPDATA%/Pricor`
    on Windows, `$XDG_DATA_HOME/pricor` elsewhere when it is set, and
    `./pricor.db` when neither is available.
    """
    if env.get("PRICOR_DB"):
        return Path(env["PRICOR_DB"])
    if env.get("LOCALAPPDATA"):
        return Path(env["LOCALAPPDATA"]) / "Pricor" / "pricor.db"
    if env.get("XDG_DATA_HOME"):
        return Path(env["XDG_DATA_HOME"]) / "pricor" / "pricor.db"
    return Path("pricor.db")


def dependencies_from_env(env: Mapping[str, str]) -> ApiDependencies:
    client = ollama_client_from_env(env)
    rate_type, fx_timeout = fx_settings_from_env(env)
    database = SqliteDatabase(database_path_from_env(env))
    stages = build_stages(env, client)
    use_case = ReuseSupplierPlan(
        FileSpreadsheetReader(),
        database.sessions,
        stages,
        GemmaPlanAdvisor(client),
        plans=database.plans,
        approvals=database,
        fx=DolarApiProvider(cache=database.fx_quotes, timeout=fx_timeout),
        default_fx_rate_type=rate_type,
    )
    reports = ReportPriceChanges(use_case.get, database.history, ReportCsvExporter())
    return ApiDependencies(use_case, web_dist=DEFAULT_WEB_DIST, reports=reports)


def app_from_env() -> FastAPI:
    return create_app(dependencies_from_env(os.environ))

