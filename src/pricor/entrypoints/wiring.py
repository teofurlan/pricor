"""Composition root: wires real adapters into the API.

Environment variables:

    PRICOR_OLLAMA_URL      base URL of the Ollama server   (default http://localhost:11434)
    PRICOR_OLLAMA_MODEL    model name                      (default gemma4:e4b)
    PRICOR_OLLAMA_TIMEOUT  seconds per model call          (default 180)
    PRICOR_DB              path of the SQLite file          (default: see `database_path_from_env`)
    PRICOR_FX_RATE_TYPE    rate type suggested for currency conversion (default oficial)
    PRICOR_FX_TIMEOUT      seconds per DolarAPI request      (default 10)

Run with: uv run uvicorn pricor.entrypoints.wiring:app_from_env --factory
"""

import os
from collections.abc import Mapping
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
from pricor.adapters.report_csv_exporter import ReportCsvExporter
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.report_price_changes import ReportPriceChanges
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
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
    stages = [
        ClassifierStage("heuristics", HeuristicColumnClassifier()),
        ClassifierStage("gemma", GemmaColumnClassifier(client)),
    ]
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

