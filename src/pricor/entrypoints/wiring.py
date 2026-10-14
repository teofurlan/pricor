"""Composition root: wires real adapters into the API.

Environment variables:

    PRICOR_OLLAMA_URL      base URL of the Ollama server   (default http://localhost:11434)
    PRICOR_OLLAMA_MODEL    model name                      (default gemma4:e4b)
    PRICOR_OLLAMA_TIMEOUT  seconds per model call          (default 180)

Run with: uv run uvicorn pricor.entrypoints.wiring:app_from_env --factory
"""

import os
from collections.abc import Mapping

from fastapi import FastAPI

from pricor.adapters.gemma_advisor import GemmaPlanAdvisor
from pricor.adapters.gemma_classifier import GemmaColumnClassifier
from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.ollama_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    OllamaClient,
)
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app


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


def dependencies_from_env(env: Mapping[str, str]) -> ApiDependencies:
    client = ollama_client_from_env(env)
    stages = [
        ClassifierStage("heuristics", HeuristicColumnClassifier()),
        ClassifierStage("gemma", GemmaColumnClassifier(client)),
    ]
    use_case = ImportFirstTime(
        FileSpreadsheetReader(),
        InMemoryImportSessionRepository(),
        stages,
        GemmaPlanAdvisor(client),
    )
    return ApiDependencies(use_case)


def app_from_env() -> FastAPI:
    return create_app(dependencies_from_env(os.environ))
