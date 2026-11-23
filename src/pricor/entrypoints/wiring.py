"""Composition root: wires real adapters into the API.

Environment variables:

    PRICOR_MODEL_PROVIDER  ollama | gemini                 (default ollama)
    PRICOR_OLLAMA_URL      base URL of the Ollama server   (default http://localhost:11434)
    PRICOR_OLLAMA_MODEL    model name                      (default gemma4:e4b)
    PRICOR_OLLAMA_TIMEOUT  seconds per model call          (default 180)
    PRICOR_GEMINI_API_KEY  Google AI Studio API key        (required when provider is gemini)
    PRICOR_GEMINI_MODEL    Gemini/Gemma chat model         (default gemma-4-26b-a4b-it)
    PRICOR_GEMINI_EMBED_MODEL Gemini embedding model       (default gemini-embedding-001)
    PRICOR_GEMINI_TIMEOUT  seconds per Gemini model call   (default 60)
    PRICOR_DEMO            enable demo mode: 1/true/yes    (default false)
    PRICOR_PRELOAD_MODELS  load Laya in the background at startup: 1/true/yes (default false)
    PRICOR_EMBED_MODEL     embedding model                 (default bge-m3)
    PRICOR_MEMORY_TOP_K    memories retrieved for Gemma    (default 3)
    PRICOR_DB              path of the SQLite file          (default: see `database_path_from_env`)
    PRICOR_LAYA_MODEL      folder of the fine-tuned Laya model (default models/laya-pricor)
    PRICOR_LAYA_DEVICE     auto | cpu | cuda               (default auto: CUDA when available)
    PRICOR_CALIBRATION     thresholds file (default: the calibrated one shipped in this package)
    PRICOR_FX_RATE_TYPE    rate type suggested for currency conversion (default oficial)
    PRICOR_FX_TIMEOUT      seconds per DolarAPI request      (default 10)
    PRICOR_WORKSPACES_DIR  turn on private workspaces (hosted demo): folder of one SQLite file
                           per visitor; PRICOR_DB is then unused       (default: off, one database)
    PRICOR_WORKSPACES_BUCKET Google Cloud Storage bucket to back up and restore workspace SQLite
                           files across restarts                       (default: off, local disk only)
    PRICOR_WORKSPACES_MAX_OPEN workspaces kept open in memory, least recently used closed first
                           (default 16)
    PRICOR_GOOGLE_CLIENT_ID OAuth client ID for optional "Continue with Google" workspace linking
                           (default: off)
    PRICOR_RATE_LIMIT_RPM  per-IP requests/min for general API and public endpoints
                           (default 120 in hosted mode, 0 = off locally)
    PRICOR_RATE_LIMIT_HEAVY_RPM per-IP requests/min for model/upload/warm-up/workspace creation
                           (default 30, capped at PRICOR_RATE_LIMIT_RPM)
    PRICOR_TRUSTED_PROXIES trusted reverse-proxy hops used from the right of X-Forwarded-For
                           (default 1 in hosted mode, 0 locally)

Run with: uv run uvicorn pricor.entrypoints.wiring:app_from_env --factory
"""

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from starlette.types import ASGIApp

from pricor.adapters.dolarapi_provider import DEFAULT_TIMEOUT_SECONDS as FX_TIMEOUT
from pricor.adapters.dolarapi_provider import DolarApiProvider
from pricor.adapters.gemini_client import (
    DEFAULT_MODEL as DEFAULT_GEMINI_MODEL,
    DEFAULT_TIMEOUT_SECONDS as DEFAULT_GEMINI_TIMEOUT_SECONDS,
    GeminiChatClient,
)
from pricor.adapters.gemini_embedder import (
    DEFAULT_MODEL as DEFAULT_GEMINI_EMBED_MODEL,
    GeminiEmbedder,
)
from pricor.adapters.gemma_advisor import GemmaPlanAdvisor
from pricor.adapters.gemma_classifier import GemmaColumnClassifier
from pricor.adapters.gemma_output_format import GemmaOutputFormat
from pricor.adapters.gemma_question_helper import GemmaQuestionHelper
from pricor.adapters.google_auth import GoogleOidcVerifier
from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.pdf_table_reader import PdfTableReader
from pricor.adapters.laya_classifier import (
    DEFAULT_MODEL_PATH,
    DEVICES,
    LayaColumnClassifier,
    laya_unavailable_reason,
)
from pricor.adapters.ollama_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    OllamaClient,
)
from pricor.adapters.ollama_embedder import DEFAULT_MODEL as DEFAULT_EMBED_MODEL
from pricor.adapters.ollama_embedder import OllamaEmbedder
from pricor.adapters.report_csv_exporter import ReportCsvExporter
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_memory_store import SqliteMemoryStore
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.application.cascade import (
    UNCALIBRATED_THRESHOLD,
    AgreementStage,
    ClassifierStage,
    Member,
    Stage,
)
from pricor.application.import_first_time import ImportFirstTime
from pricor.application.manage_memory import ManageMemory
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.application.report_price_changes import ReportPriceChanges
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.domain.fx import MARKET_RATE_TYPES
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.entrypoints.calibration_file import DEFAULT_CALIBRATION_PATH, load_calibration
from pricor.entrypoints.rate_limit import (
    DEFAULT_GENERAL_RPM,
    DEFAULT_HEAVY_RPM,
    RateLimitConfig,
    RateLimitMiddleware,
)
from pricor.entrypoints.web_app import DEFAULT_WEB_DIST
from pricor.entrypoints.workspace_accounts import WorkspaceAccountStore
from pricor.entrypoints.workspaces import (
    DEFAULT_MAX_OPEN,
    OpenWorkspace,
    WorkspaceRegistry,
    create_workspace_app,
)
from pricor.ports.chat_client import ChatClient
from pricor.ports.embedder import Embedder
from pricor.ports.workspace_backup import NoWorkspaceBackup, WorkspaceBackup


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


def gemini_client_from_env(env: Mapping[str, str]) -> GeminiChatClient:
    api_key = env.get("PRICOR_GEMINI_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError("PRICOR_GEMINI_API_KEY is required when PRICOR_MODEL_PROVIDER is 'gemini'")
    try:
        timeout = float(env.get("PRICOR_GEMINI_TIMEOUT", DEFAULT_GEMINI_TIMEOUT_SECONDS))
    except ValueError as error:
        raise ValueError("PRICOR_GEMINI_TIMEOUT must be a number of seconds") from error
    return GeminiChatClient(
        api_key=api_key.strip(),
        model=env.get("PRICOR_GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        timeout=timeout,
    )


PROVIDERS = ("ollama", "gemini")


def model_provider_from_env(env: Mapping[str, str]) -> str:
    """`PRICOR_MODEL_PROVIDER`, ignoring case and spaces; blank or unset means `ollama`."""
    provider = (env.get("PRICOR_MODEL_PROVIDER") or "").strip().lower() or "ollama"
    if provider not in PROVIDERS:
        raise ValueError(f"PRICOR_MODEL_PROVIDER must be 'ollama' or 'gemini', got {provider!r}")
    return provider


def chat_client_from_env(env: Mapping[str, str]) -> ChatClient:
    if model_provider_from_env(env) == "gemini":
        return gemini_client_from_env(env)
    return ollama_client_from_env(env)


def embedder_from_env(env: Mapping[str, str], chat_client: ChatClient) -> Embedder:
    """The memory embedder for the same provider, sharing the chat client's server and timeout."""
    if isinstance(chat_client, GeminiChatClient):
        return GeminiEmbedder(
            api_key=env.get("PRICOR_GEMINI_API_KEY", "").strip(),
            model=env.get("PRICOR_GEMINI_EMBED_MODEL", DEFAULT_GEMINI_EMBED_MODEL),
            timeout=chat_client.timeout,
            base_url=chat_client.base_url,
        )
    if isinstance(chat_client, OllamaClient):
        return OllamaEmbedder(
            base_url=chat_client.base_url,
            model=env.get("PRICOR_EMBED_MODEL", DEFAULT_EMBED_MODEL),
            timeout=chat_client.timeout,
        )
    raise TypeError(f"no embedder for chat client {type(chat_client).__name__}")


def demo_from_env(env: Mapping[str, str]) -> bool:
    val = env.get("PRICOR_DEMO", "").strip().lower()
    return val in ("1", "true", "yes")


def preload_from_env(env: Mapping[str, str]) -> bool:
    return env.get("PRICOR_PRELOAD_MODELS", "").strip().lower() in ("1", "true", "yes")


def preload_warm_up(stages: list[Stage]) -> Callable[[], None] | None:
    """Warm up the Laya classifier through the existing stage, or None when Laya cannot run."""
    for stage in stages:
        if stage.skipped_reason is not None:
            continue
        members = (
            [stage.classifier]
            if isinstance(stage, ClassifierStage)
            else [stage.first.classifier, stage.second.classifier]
        )
        for classifier in members:
            if isinstance(classifier, LayaColumnClassifier):
                return classifier.warm_up
    return None


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
    client: ChatClient,
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
    is_gemini_without_explicit_cal = (
        model_provider_from_env(env) == "gemini" and not env.get("PRICOR_CALIBRATION")
    )

    def classifier_stage(name: str, classifier, skipped_reason: str | None = None) -> ClassifierStage:
        if name == "gemma" and is_gemini_without_explicit_cal:
            return ClassifierStage(name, classifier, UNCALIBRATED_THRESHOLD, False, skipped_reason)
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


def memory_top_k_from_env(env: Mapping[str, str]) -> int:
    raw = env.get("PRICOR_MEMORY_TOP_K", "3")
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError("PRICOR_MEMORY_TOP_K must be a positive integer") from error
    if value <= 0:
        raise ValueError("PRICOR_MEMORY_TOP_K must be a positive integer")
    return value


@dataclass(frozen=True)
class SharedServices:
    """What every workspace shares: the model client, embedder, cascade and settings."""

    provider: str
    client: ChatClient
    stages: list[Stage]
    embedder: Embedder
    rate_type: str
    fx_timeout: float
    memory_top_k: int
    demo: bool
    warm_up: Callable[[], None] | None


def shared_services_from_env(env: Mapping[str, str]) -> SharedServices:
    client = chat_client_from_env(env)
    rate_type, fx_timeout = fx_settings_from_env(env)
    stages = build_stages(env, client)
    return SharedServices(
        provider=model_provider_from_env(env),
        client=client,
        stages=stages,
        embedder=embedder_from_env(env, client),
        rate_type=rate_type,
        fx_timeout=fx_timeout,
        memory_top_k=memory_top_k_from_env(env),
        demo=demo_from_env(env),
        warm_up=preload_warm_up(stages) if preload_from_env(env) else None,
    )


def database_dependencies(
    database: SqliteDatabase,
    shared: SharedServices,
    *,
    web_dist: Path | None = None,
    warm_up: Callable[[], None] | None = None,
) -> ApiDependencies:
    """The API over one database (the local one, or one visitor's workspace)."""
    client = shared.client
    memory = ManageMemory(
        SqliteMemoryStore(database, shared.embedder.model), shared.embedder, database.sessions.get
    )
    use_case = ReuseSupplierPlan(
        FileSpreadsheetReader(),
        database.sessions,
        shared.stages,
        GemmaPlanAdvisor(client),
        plans=database.plans,
        approvals=database,
        fx=DolarApiProvider(cache=database.fx_quotes, timeout=shared.fx_timeout),
        default_fx_rate_type=shared.rate_type,
        memory=memory,
        memory_top_k=shared.memory_top_k,
        output_formats=database.output_format,
    )
    reports = ReportPriceChanges(use_case.get, database.history, ReportCsvExporter())
    return ApiDependencies(
        use_case,
        web_dist=web_dist,
        reports=reports,
        memory=memory,
        memory_top_k=shared.memory_top_k,
        question_helper=GemmaQuestionHelper(client),
        output_format=ManageOutputFormat(
            FileSpreadsheetReader(), database.output_format, HeuristicOutputFormat(),
            GemmaOutputFormat(client), pdf_reader=PdfTableReader(),
        ),
        model_provider=shared.provider,
        demo=shared.demo,
        warm_up=warm_up,
    )


def dependencies_from_env(env: Mapping[str, str]) -> ApiDependencies:
    shared = shared_services_from_env(env)
    return database_dependencies(
        SqliteDatabase(database_path_from_env(env)), shared,
        web_dist=DEFAULT_WEB_DIST, warm_up=shared.warm_up,
    )


def workspaces_dir_from_env(env: Mapping[str, str]) -> Path | None:
    value = env.get("PRICOR_WORKSPACES_DIR", "").strip()
    return Path(value) if value else None


def workspaces_max_open_from_env(env: Mapping[str, str]) -> int:
    raw = env.get("PRICOR_WORKSPACES_MAX_OPEN", "").strip()
    if not raw:
        return DEFAULT_MAX_OPEN
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError("PRICOR_WORKSPACES_MAX_OPEN must be a whole number of at least 1")
    return value


def workspace_backup_from_env(env: Mapping[str, str]) -> WorkspaceBackup:
    bucket = env.get("PRICOR_WORKSPACES_BUCKET", "").strip()
    if bucket:
        from pricor.adapters.gcs_workspace_backup import GcsWorkspaceBackup
        return GcsWorkspaceBackup(bucket)
    return NoWorkspaceBackup()


def google_client_id_from_env(env: Mapping[str, str]) -> str | None:
    value = env.get("PRICOR_GOOGLE_CLIENT_ID", "").strip()
    return value or None


def workspace_app_from_env(env: Mapping[str, str], directory: Path) -> ASGIApp:
    """Hosted demo: a private database per visitor, the models built once and shared."""
    shared = shared_services_from_env(env)

    def open_workspace(path: Path) -> OpenWorkspace:
        database = SqliteDatabase(path)
        return OpenWorkspace(create_app(database_dependencies(database, shared)), database.close)

    backup = workspace_backup_from_env(env)
    registry = WorkspaceRegistry(
        directory, open_workspace, backup, workspaces_max_open_from_env(env)
    )
    google_client_id = google_client_id_from_env(env)
    accounts = WorkspaceAccountStore(directory, backup) if google_client_id else None
    google_verifier = GoogleOidcVerifier(google_client_id) if google_client_id else None
    public = ApiDependencies(
        ImportFirstTime(FileSpreadsheetReader(), InMemoryImportSessionRepository(), []),
        web_dist=DEFAULT_WEB_DIST,
        model_provider=shared.provider,
        demo=shared.demo,
        warm_up=shared.warm_up,
        google_client_id=google_client_id,
    )
    return create_workspace_app(public, registry, accounts=accounts, google_verifier=google_verifier)


def _parse_int_env(env: Mapping[str, str], name: str, *, minimum: int, label: str) -> int | None:
    raw = env.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        value = minimum - 1
    if value < minimum:
        raise ValueError(f"{name} must be {label}")
    return value


def rate_limit_from_env(env: Mapping[str, str], *, hosted: bool) -> RateLimitConfig | None:
    """Per-IP rate-limit settings: enabled by default in hosted mode, off locally unless set."""
    general = _parse_int_env(
        env, "PRICOR_RATE_LIMIT_RPM", minimum=0, label="a non-negative whole number"
    )
    heavy = _parse_int_env(
        env, "PRICOR_RATE_LIMIT_HEAVY_RPM", minimum=1, label="a whole number of at least 1"
    )
    trusted = _parse_int_env(
        env, "PRICOR_TRUSTED_PROXIES", minimum=0, label="a non-negative whole number"
    )

    general_rpm = (DEFAULT_GENERAL_RPM if hosted else 0) if general is None else general
    if general_rpm == 0:
        return None
    heavy_rpm = min(DEFAULT_HEAVY_RPM, general_rpm) if heavy is None else heavy
    trusted_proxies = (1 if hosted else 0) if trusted is None else trusted
    return RateLimitConfig(
        general_rpm=general_rpm,
        heavy_rpm=heavy_rpm,
        trusted_proxies=trusted_proxies,
    )


def app_for_env(env: Mapping[str, str]) -> ASGIApp:
    directory = workspaces_dir_from_env(env)
    hosted = directory is not None
    app: ASGIApp = (
        workspace_app_from_env(env, directory)
        if directory is not None
        else create_app(dependencies_from_env(env))
    )
    rate_limit = rate_limit_from_env(env, hosted=hosted)
    if rate_limit is not None:
        return RateLimitMiddleware(app, rate_limit)
    return app


def configure_logging() -> None:
    """Send Pricor's INFO lines (stage timings, model loads) to stderr; uvicorn only sets up its own."""
    logger = logging.getLogger("pricor")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def app_from_env() -> ASGIApp:
    configure_logging()
    return app_for_env(os.environ)
