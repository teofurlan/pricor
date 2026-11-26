"""HTTP API for the first-import flow (FastAPI).

All bodies are JSON except the upload, which is multipart. Session state is
always returned in the same shape (`id`, `status`, `header`, `columns`,
`role_issues`, `questions`, `answers`, `notices`, `approved`, `mode`,
`based_on_plan_version`, `changes`); follow `status`:

    header_choice_required      -> PUT  /imports/{id}/header
    role_confirmation_required  -> PUT  /imports/{id}/roles
    questions_pending           -> POST /imports/{id}/answers (one per question)
    fx_rate_required            -> PUT  /imports/{id}/fx (type a rate) or POST /imports/{id}/fx/refresh
    ready_for_preview           -> GET  /imports/{id}/preview, POST /imports/{id}/approve
    approved                    -> frozen

Endpoints:

    POST /output-format           multipart: file (.csv/.xlsx/.xlsm/.xls/.pdf; a PDF yields the
                                  headers of its first table), [sheet] -> 201 proposed format
    GET  /output-format           saved proposed or confirmed format (404 when absent)
    PUT  /output-format/mapping   {"sources": ["field:supplier_code", "empty", "constant:..."]}
                                  -> confirmed format (422 for wrong count or invalid source)
    PUT  /output-format           {"columns": [{"name": "SKU", "source": "field:supplier_code",
                                  "template_index": 0 | null, "kind": "code" | null}]} -> confirmed
                                  format with exactly these columns, in this order (422 for a blank,
                                  long or repeated name, an invalid source, an unknown template
                                  column, an unknown kind or a non-numeric number/price constant).
                                  kind is text|description|code|number|price; absent/null takes the
                                  kind the source suggests. Every format body also carries
                                  "fit": {"matched", "total", "unmatched": [names], "mismatch"}
    DELETE /output-format         remove the store-wide format -> 204
    POST /sheets                  multipart: file -> {"sheets": ["..."]}
    GET  /suppliers               {"suppliers": ["..."]}  saved suppliers with an approved plan
    POST /imports                 multipart: file, supplier_name, [sheet], [language],
                                  [force_first_import]  -> 201 state
    GET  /imports/{id}            current state
    GET  /imports/{id}/sample     ?limit=5 (1..20) -> {"header": [...], "rows": [[...], ...]}
    PUT  /imports/{id}/header     {"row_index": 3 | null}   (null = the sheet has no header)
    PUT  /imports/{id}/roles      {"roles": {"2": "cost_price"}}   (column index -> role)
    POST /imports/{id}/answers    {"question_id": "currency", "option": "ARS"}
    POST /imports/{id}/questions/{question_id}/ask
                                  {"message": "...", "history": [{"role": "user|model", "text": "..."}]}
                                  -> {"reply": "...", "suggested_option": "yes" | null}
    PUT  /imports/{id}/fx         {"rate": "1420,50"}  a manual exchange rate for this run
    POST /imports/{id}/fx/refresh ask the live source for the plan's rate again
    GET  /imports/{id}/preview    ?offset=0&limit=50&q=&status=all  -> per-row original, trace, final values
    POST /imports/{id}/approve    freezes the plan and the result
    GET  /imports/{id}/export     ?format=csv|xlsx (default csv)  -> the products file
    GET  /imports/{id}/rejected   ?format=csv|xlsx (default csv)  -> the rejected-rows report
    POST /imports/combined-export {"session_ids": ["<id>", ...], "format": "csv"|"xlsx",
                                  "kind": "products"|"rejected"}  -> one file, 1 to 50 approved
                                  imports in the given order, a `supplier` column first (409 when
                                  the files were approved with different output formats)
    POST /events                  {"event": "visit"|"import_started"|"approved"|"downloaded",
                                  "group": "<id>"|null} -> 204; logs one `pricor_event` line, no
                                  workspace needed (422 invalid_input for an unknown event)
    GET  /imports/{id}/report     ?threshold=0.30  -> what changed since the previous import
    GET  /imports/{id}/report/export  ?threshold=0.30&format=csv  -> the same, as a file

Currency conversion: when the prices include a foreign currency the `fx_conversion` question
asks whether to convert to ARS and with which rate (`keep`, `<rate_type>:<side>` such as
`oficial:venta`, or `manual`). The plan stores only that choice; each run snapshots its own
rate, reported as `fx` (`null` when the plan does not convert): `snapshot` is `null` until a
rate is available (`error` says why the live source failed), and `snapshot.stale` flags a
cached quote used offline. Converted values appear next to the originals, never in place of
them. The price report keeps comparing in each record's own currency.

A supplier with an approved plan is reused automatically: `mode` is `"reuse"`,
`based_on_plan_version` names the plan, and `changes` lists what differs in the new file
(`moved`, `retyped`, `new`, `missing` columns, `sheet_changed`, `header_row_changed`).
Columns the plan settled have `decided_by: "saved_plan"`. Send `force_first_import=true` to
start from scratch instead; `mode` is then `"first_import"`.

The price-change report compares an approved import with the supplier's previous approved
one by `supplier_code`, in each record's own currency. `threshold` is a ratio (`0.30` is
30%, the default). It is a 409 `no_previous_import` for a supplier's first import and a 409
`invalid_operation` before approval; a bad threshold is a 422. Costs are exact decimal
strings and `*_pct` fields are percentages rounded to two decimals for display.

Both downloads are attachments (`Content-Disposition`) and exist only for approved
sessions (409 otherwise); an unknown `format` is a 422. The XLSX export carries the
rejected rows as a second sheet. Column order and text/number rules are in
`pricor.ports.exporter` and the exporter modules.

`GET /samples` lists the synthetic sample price lists shipped with the package (`id`,
`file_name`, `supplier_name`, `week`, and `title`/`description` keyed by language `en`/`es`);
`GET /samples/{id}` downloads one as XLSX, or 404 `sample_not_found`.

Errors share one body, `{"error": {"code": "...", "message": "..."}}`, with
404 (unknown session), 409 (operation not allowed in this state), 413 (file too
large), 415 (unsupported file type) and 422 (invalid input or unreadable file).
Nothing a model says is ever executed: questions are deterministic and a model
hypothesis is only a suggestion.

Output templates read the first non-empty row as names (blank names become Column N)
and up to five following rows as samples. POST replaces the saved format and leaves
it proposed, never active until PUT confirms every column. GET, POST and PUT return
{name, state, fields, columns: [{index, name, samples, proposal: {source,
proposed_by, confidence}, source}]}; source is null until confirmation. Sources
are field:<name> from fields (the complete product field list, including conversion
and source_row), empty, or constant:<1–200 characters>. Model proposals are validated
and fall back to header heuristics on failure; confidence is uncalibrated. Confirmed
formats affect only product downloads, never the rejected report. Deleting the format
or uploading an unconfirmed replacement restores the standard products format.

Question help is read-only, including for answered questions: only POST /answers
confirms an option. The message is trimmed to 1–500 characters; optional history
contains at most 6 earlier turns of that same question, each at most 1,200
characters. Replies are non-empty and at most 1,200 characters; suggested_option
must be one of that question's option tokens or null. Unknown sessions or unasked
question ids return 404, invalid bodies 422, and unavailable or invalid model
replies 503 with code model_unavailable in the same error envelope.
"""

import logging
import re
import shutil
import tempfile
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pricor.application.errors import (
    AcceptedSuggestionConflictError,
    ApplicationError,
    EmbedderUnavailableError,
    InvalidInputError,
    InvalidOperationError,
    MemoryUnavailableError,
    NoAcceptedRowsError,
    NoPreviousImportError,
    QuestionNotFoundError,
)
from pricor.adapters.csv_exporter import CsvExporter
from pricor.adapters.xlsx_exporter import XlsxExporter
from pricor.application.ask_about_question import AskAboutQuestion
from pricor.application.export_import import ExportedFile, ExportImport
from pricor.application.import_first_time import ImportFirstTime
from pricor.application.manage_memory import InvalidMemoryTextError, ManageMemory
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.application.questions import Question, option_groups
from pricor.application.report_price_changes import (
    ImportComparison,
    ReportPriceChanges,
    parse_threshold,
)
from pricor.domain.price_report import PriceChange, ProductPrice, percent_text
from pricor.domain.roles import ColumnRole
from pricor.ports.import_session import ImportSession, PlanChange, PreviewPage, PreviewRow
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.memory import Memory, MemoryNotFoundError
from pricor.ports.plan_repository import PlanRepository
from pricor.ports.price_history import ImportSummary
from pricor.ports.question_model import Option
from pricor.ports.output_format import OUTPUT_FIELDS, OutputFormat, OutputFormatNotFoundError, check_fit
from pricor.ports.model_errors import ModelError
from pricor.ports.question_helper import (
    MAX_HISTORY_TURNS,
    MAX_MESSAGE_LENGTH,
    MAX_REPLY_LENGTH,
    QuestionHelper,
    QuestionTurn,
)
from pricor.entrypoints.web_app import install_web_app
from pricor.samples import SAMPLES, XLSX_CONTENT_TYPE, find_sample
from pricor.ports.spreadsheet import (
    FileTooLargeError,
    SpreadsheetError,
    SpreadsheetReader,
    TooManyRowsError,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)
events_logger = logging.getLogger("pricor.events")
EVENT_NAMES = frozenset({"visit", "import_started", "approved", "downloaded"})
_GROUP = re.compile(r"[a-z0-9_-]{1,40}")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset({".csv", ".xlsx", ".xlsm", ".xls", ".pdf"})
TEMPLATE_EXTENSIONS = ALLOWED_EXTENSIONS
_CHUNK = 1024 * 1024
# Letters in any script, digits, spaces, dots and dashes survive; separators and the
# characters Windows forbids in file names do not.
_UNSAFE = re.compile(r"[^\w .-]+")


@dataclass(frozen=True)
class ApiDependencies:
    use_case: ImportFirstTime
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    upload_dir: Path | None = None  # parent for temporary uploads; the system default if None
    exports: ExportImport | None = None  # CSV and XLSX exporters over the use case if None
    web_dist: Path | None = None  # built web app to serve at `/`; API only if None
    reports: ReportPriceChanges | None = None  # price-change reports; unavailable if None
    memory: ManageMemory | None = None  # semantic memory; unavailable if None
    memory_top_k: int = 3  # retrieval count used by the later Gemma integration
    reader: SpreadsheetReader | None = None
    question_helper: QuestionHelper | None = None  # read-only model explanations; optional
    output_format: ManageOutputFormat | None = None  # one persistent store-wide template
    model_provider: str = "ollama"
    demo: bool = False
    warm_up: Callable[[], None] | None = None  # run once in the background at startup
    workspaces: bool = False  # private workspace per visitor (hosted demo); see workspaces.py
    warm_up_timeout: float = 120.0  # seconds `POST /warm-up` holds a request open for the load
    google_client_id: str | None = None  # optional OAuth client ID for Google Sign-In
    plans: PlanRepository | None = None  # saved supplier plans; falls back to use_case._plans


class OutputMappingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Annotated[str, StringConstraints(strict=True)]]


class OutputColumnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strict=True)]
    source: Annotated[str, StringConstraints(strict=True)]
    template_index: int | None = None
    kind: Annotated[str, StringConstraints(strict=True)] | None = None


class OutputColumnsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[OutputColumnBody]


class CombinedExportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ids: list[Annotated[str, StringConstraints(strict=True)]]
    format: Annotated[str, StringConstraints(strict=True)]
    kind: Annotated[str, StringConstraints(strict=True)] = "products"


class HeaderBody(BaseModel):
    row_index: int | None


class RolesBody(BaseModel):
    roles: dict[int, ColumnRole]


class AnswerBody(BaseModel):
    question_id: str
    option: str


class QuestionTurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "model"]
    text: Annotated[str, StringConstraints(strict=True, max_length=MAX_REPLY_LENGTH)]


class AskQuestionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH),
    ]
    history: list[QuestionTurnBody] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class RateBody(BaseModel):
    rate: str


class MemoryNoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    supplier_name: str | None = None


class AcceptedSuggestionMemoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    question_id: str


class EditMemoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


# -- serialization ----------------------------------------------------------------


def _option(option: Option, groups: dict[str, str] | None) -> dict[str, Any]:
    body: dict[str, Any] = {"token": option.token, "label": option.label.as_dict()}
    if groups is not None:
        body["group"] = groups[option.token]
    return body


def _question(question: Question) -> dict[str, Any]:
    suggestion = question.suggestion
    groups = option_groups(question)
    return {
        "id": question.id.value,
        "text": question.text.as_dict(),
        "options": [_option(option, groups) for option in question.options],
        "allows_custom": question.allows_custom,
        "reason": question.reason,
        "model_phrasing": question.model_phrasing,
        "suggestion": None
        if suggestion is None
        else {
            "suggested_by": suggestion.suggested_by,
            "option": suggestion.option,
            "confidence": suggestion.confidence,
            "calibrated": suggestion.calibrated,
            "memory_ids": suggestion.memory_ids,
            "evidence": [
                {"column_index": item.column_index, "sample": item.sample}
                for item in suggestion.evidence
            ],
        },
    }


def _change(change: PlanChange) -> dict[str, Any]:
    return {
        "kind": change.kind,
        "header": change.header,
        "old_index": change.old_index,
        "new_index": change.new_index,
        "old_type": change.old_type,
        "new_type": change.new_type,
        "used_by_plan": change.used_by_plan,
        "role": change.role,
        "old_value": change.old_value,
        "new_value": change.new_value,
    }


def output_format_body(output_format: OutputFormat) -> dict[str, Any]:
    fit = check_fit(output_format)
    return {
        **asdict(output_format),
        "fields": list(OUTPUT_FIELDS),
        "fit": {
            "matched": fit.matched, "total": fit.total,
            "unmatched": list(fit.unmatched), "mismatch": fit.mismatch,
        },
    }


def memory_body(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "text": memory.text,
        "supplier_name": memory.supplier_name,
        "source": memory.source,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
    }


def _fx_state(session: ImportSession) -> dict[str, Any] | None:
    step = session.conversion
    if step is None:
        return None
    snapshot = session.fx_snapshot
    return {
        "from": step.from_currency,
        "to": step.to_currency,
        "rate_type": step.rate_type,
        "side": step.side,
        "error": session.fx_error,
        "snapshot": None
        if snapshot is None
        else {
            "rate": str(snapshot.rate),
            "rate_type": snapshot.rate_type,
            "side": snapshot.side,
            "source": snapshot.source,
            "quoted_at": snapshot.quoted_at.isoformat(),
            "date": snapshot.date,
            "stale": snapshot.stale,
        },
    }


def session_state(session: ImportSession) -> dict[str, Any]:
    profile = session.profile
    samples = {column.index: list(column.samples) for column in profile.columns}
    quantity_discounts = {column.index for column in profile.columns if column.quantity_discount}
    empty_rows = {column.index: column.empty_rows for column in profile.columns}
    data_rows = {column.index: column.data_rows for column in profile.columns}
    return {
        "id": session.id,
        "status": session.status.value,
        "supplier_name": session.supplier_name,
        "file_name": session.file_name,
        "sheet_name": session.sheet_name,
        "header": {
            "row_index": profile.header_row,
            "confidence": profile.header_confidence,
            "ambiguous": profile.header_ambiguous,
            "candidates": [
                {"row_index": item.row_index, "file_row": item.file_row, "cells": list(item.cells)}
                for item in session.header_candidates
            ],
        },
        "columns": [
            {
                "index": column.index,
                "header": column.header,
                "role": None if column.role is None else column.role.value,
                "decided_by": column.decided_by,
                "score": column.score,
                "rationale": column.rationale,
                "samples": samples.get(column.index, []),
                "quantity_discount": column.index in quantity_discounts,
                "empty_rows": empty_rows.get(column.index, 0),
                "data_rows": data_rows.get(column.index, 0),
                "proposals": [
                    {
                        "stage": item.stage,
                        "role": item.role.value,
                        "score": item.score,
                        "rationale": item.rationale,
                    }
                    for item in column.proposals
                ],
            }
            for column in session.columns
        ],
        "role_issues": list(session.role_issues),
        "questions": [_question(question) for question in session.questions],
        "answers": {parameter.value: token for parameter, token in session.answers.items()},
        "notices": [
            {"code": item.code, "message": item.message, "stage": item.stage}
            for item in session.notices
        ],
        "approved": session.approved,
        "mode": session.mode,
        "based_on_plan_version": session.based_on_plan_version,
        "changes": [_change(item) for item in session.changes],
        "fx": _fx_state(session),
    }


def _trace(item: PreviewRow) -> list[dict[str, Any]]:
    """The value after each step; the conversion also carries what it was computed from.

    The engine converts the unrounded cost, which is the step just before
    "rounding", so showing it next to the rate explains a converted figure that
    does not match the rounded cost.
    """
    steps = [{"step": step.step, "value": step.value} for step in item.trace]
    names = [step.step for step in item.trace]
    if "rounding" in names and item.record is not None and item.record.get("fx_rate"):
        position = names.index("rounding")
        if position > 0 and steps[-1]["step"] == "convert_currency":
            steps[-1]["source"] = steps[position - 1]["value"]
            steps[-1]["rate"] = item.record["fx_rate"]
    return steps


def preview_body(page: PreviewPage) -> dict[str, Any]:
    return {
        "offset": page.offset,
        "limit": page.limit,
        "total_items": page.total_items,
        "totals": page.totals,
        "items": [
            {
                "row_number": item.row_number,
                "status": item.status,
                "original": list(item.original),
                "trace": _trace(item),
                "record": item.record,
                "reasons": list(item.reasons),
            }
            for item in page.items
        ],
    }


# -- errors -----------------------------------------------------------------------


def _money(value: Decimal) -> str:
    return format(value, "f")


def _change_item(item: PriceChange) -> dict[str, Any]:
    return {
        "supplier_code": item.supplier_code,
        "description": item.description,
        "currency": item.currency,
        "previous_cost": _money(item.previous_cost),
        "current_cost": _money(item.current_cost),
        "change": _money(item.change),
        "change_pct": None if item.change_ratio is None else percent_text(item.change_ratio),
        "anomaly": item.anomaly,
    }


def _product_item(item: ProductPrice) -> dict[str, Any]:
    return {
        "supplier_code": item.supplier_code,
        "description": item.description,
        "currency": item.currency,
        "unit_cost_net": _money(item.unit_cost_net),
    }


def _import_item(summary: ImportSummary) -> dict[str, Any]:
    return {
        "import_id": summary.import_id,
        "imported_at": summary.imported_at.isoformat(),
        "record_count": summary.record_count,
    }


def report_body(comparison: ImportComparison) -> dict[str, Any]:
    """The price-change report as JSON: money as exact strings, percentages rounded for display."""
    report, totals = comparison.report, comparison.report.summary
    return {
        "import_id": comparison.current.import_id,
        "supplier_name": comparison.current.supplier_name,
        "threshold": str(report.threshold),
        "previous_import": _import_item(comparison.previous),
        "current_import": _import_item(comparison.current),
        "summary": {
            "unchanged": totals.unchanged,
            "increases": totals.increases,
            "decreases": totals.decreases,
            "from_zero": totals.from_zero,
            "new_products": totals.new_products,
            "discontinued": totals.discontinued,
            "currency_changed": totals.currency_changed,
            "ambiguous": totals.ambiguous,
            "anomalies": totals.anomalies,
            "median_change_pct": None
            if totals.median_change is None
            else percent_text(totals.median_change),
        },
        "increases": [_change_item(item) for item in report.increases],
        "decreases": [_change_item(item) for item in report.decreases],
        "from_zero": [_change_item(item) for item in report.from_zero],
        "anomalies": [_change_item(item) for item in report.anomalies],
        "new_products": [_product_item(item) for item in report.new_products],
        "discontinued": [_product_item(item) for item in report.discontinued],
        "currency_changed": [
            {
                "supplier_code": item.supplier_code,
                "description": item.description,
                "previous_currency": item.previous_currency,
                "current_currency": item.current_currency,
                "previous_cost": _money(item.previous_cost),
                "current_cost": _money(item.current_cost),
            }
            for item in report.currency_changed
        ],
        "ambiguous_codes": [
            {
                "supplier_code": item.supplier_code,
                "previous_count": item.previous_count,
                "current_count": item.current_count,
            }
            for item in report.ambiguous_codes
        ],
    }


def _download(file: ExportedFile) -> Response:
    # Filenames are ASCII slugs built by the use case: safe inside a quoted header value.
    return Response(
        file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
    )


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _spreadsheet_status(error: SpreadsheetError) -> tuple[int, str]:
    if isinstance(error, UnsupportedFormatError):
        return 415, "unsupported_format"
    if isinstance(error, FileTooLargeError):
        return 413, "file_too_large"
    if isinstance(error, TooManyRowsError):
        return 422, "too_many_rows"
    return 422, "unreadable_file"


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotFoundError)
    async def not_found(_: Request, error: SessionNotFoundError) -> JSONResponse:
        return _error(404, "session_not_found", str(error))

    @app.exception_handler(OutputFormatNotFoundError)
    async def output_format_not_found(_: Request, error: OutputFormatNotFoundError) -> JSONResponse:
        return _error(404, "output_format_not_found", str(error))

    @app.exception_handler(MemoryNotFoundError)
    async def memory_not_found(_: Request, error: MemoryNotFoundError) -> JSONResponse:
        return _error(404, "memory_not_found", str(error))

    @app.exception_handler(QuestionNotFoundError)
    async def question_not_found(_: Request, error: QuestionNotFoundError) -> JSONResponse:
        return _error(404, "question_not_found", str(error))

    @app.exception_handler(AcceptedSuggestionConflictError)
    async def suggestion_conflict(
        _: Request, error: AcceptedSuggestionConflictError
    ) -> JSONResponse:
        return _error(409, "accepted_suggestion_conflict", str(error))

    @app.exception_handler(InvalidMemoryTextError)
    async def invalid_memory_text(_: Request, error: InvalidMemoryTextError) -> JSONResponse:
        return _error(422, "invalid_memory_text", str(error))

    @app.exception_handler(MemoryUnavailableError)
    async def memory_unavailable(_: Request, error: MemoryUnavailableError) -> JSONResponse:
        return _error(503, "memory_unavailable", str(error))

    @app.exception_handler(EmbedderUnavailableError)
    async def embedder_unavailable(_: Request, error: EmbedderUnavailableError) -> JSONResponse:
        return _error(503, "embedder_unavailable", str(error))

    @app.exception_handler(ModelError)
    async def model_unavailable(_: Request, error: ModelError) -> JSONResponse:
        return _error(503, "model_unavailable", str(error))

    @app.exception_handler(NoPreviousImportError)
    async def no_previous_import(_: Request, error: NoPreviousImportError) -> JSONResponse:
        return _error(409, "no_previous_import", str(error))

    @app.exception_handler(NoAcceptedRowsError)
    async def no_accepted_rows(_: Request, error: NoAcceptedRowsError) -> JSONResponse:
        return _error(409, "no_accepted_rows", str(error))

    @app.exception_handler(InvalidOperationError)
    async def conflict(_: Request, error: InvalidOperationError) -> JSONResponse:
        return _error(409, "invalid_operation", str(error))

    @app.exception_handler(InvalidInputError)
    async def invalid(_: Request, error: InvalidInputError) -> JSONResponse:
        return _error(422, "invalid_input", str(error))

    @app.exception_handler(ApplicationError)
    async def application(_: Request, error: ApplicationError) -> JSONResponse:
        return _error(422, "application_error", str(error))

    @app.exception_handler(SpreadsheetError)
    async def spreadsheet(_: Request, error: SpreadsheetError) -> JSONResponse:
        status, code = _spreadsheet_status(error)
        return _error(status, code, str(error))

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'][1:]) or item['loc'][0]}: {item['msg']}"
            for item in error.errors()
        )
        return _error(422, "invalid_request", problems)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception) -> JSONResponse:
        return _error(500, "internal_error", "unexpected server error")


# -- uploads ----------------------------------------------------------------------


def _safe_name(filename: str | None) -> str:
    base = (filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("_", base).strip("._ ") or "upload"
    return name[:100]


def _store_upload(
    upload: UploadFile, directory: Path, limit: int, allowed: frozenset[str] = ALLOWED_EXTENSIONS
) -> Path:
    name = _safe_name(upload.filename)
    if Path(name).suffix.lower() not in allowed:
        raise UnsupportedFormatError(
            f"unsupported file type; use one of: {', '.join(sorted(allowed))}"
        )
    target = directory / name
    written = 0
    with target.open("wb") as handle:
        while chunk := upload.file.read(_CHUNK):
            written += len(chunk)
            if written > limit:
                raise FileTooLargeError(f"the file is larger than {limit // (1024 * 1024)} MB")
            handle.write(chunk)
    return target


# -- app --------------------------------------------------------------------------


class _WarmUp:
    """Runs the warm-up at most once, in a daemon thread, whoever asks first (startup or a visit)."""

    def __init__(self, warm_up: Callable[[], None]):
        self._warm_up = warm_up
        self._lock = threading.Lock()
        self._started = False
        self._done = threading.Event()
        self._ok = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._run, name="model-warm-up", daemon=True).start()

    def _run(self) -> None:
        try:
            self._warm_up()
            self._ok = True
        except Exception as error:  # a failed warm-up only costs the first import its load time
            logger.warning("model warm-up failed (%s: %s); models load on first use", type(error).__name__, error)
        finally:
            self._done.set()

    def wait(self, timeout: float) -> str:
        self.start()
        if not self._done.wait(timeout):
            return "loading"
        return "ready" if self._ok else "unavailable"


def create_app(
    dependencies: ApiDependencies, extra_routes: Callable[[FastAPI], None] | None = None
) -> FastAPI:
    warm_up = _WarmUp(dependencies.warm_up) if dependencies.warm_up is not None else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if warm_up is not None:
            warm_up.start()
        yield

    app = FastAPI(title="Pricor", version="0.1.0", lifespan=lifespan)
    use_case = dependencies.use_case
    reader = dependencies.reader or getattr(use_case, "_reader", None)
    plans = dependencies.plans or getattr(use_case, "_plans", None)
    question_help = AskAboutQuestion(use_case.get, dependencies.question_helper)
    exports = dependencies.exports or ExportImport(
        use_case.get, [CsvExporter(), XlsxExporter()],
        output_format=dependencies.output_format.store if dependencies.output_format else None,
    )
    _install_error_handlers(app)

    def output_formats() -> ManageOutputFormat:
        if dependencies.output_format is None:
            raise InvalidOperationError("output format storage is not configured")
        return dependencies.output_format

    @app.post("/output-format", status_code=201)
    def upload_output_format(
        file: UploadFile = File(...), sheet: str | None = Form(None),
    ) -> dict[str, Any]:
        manager = output_formats()
        parent = None if dependencies.upload_dir is None else str(dependencies.upload_dir)
        directory = Path(tempfile.mkdtemp(prefix="pricor-template-", dir=parent))
        try:
            path = _store_upload(file, directory, dependencies.max_upload_bytes, TEMPLATE_EXTENSIONS)
            result = manager.upload(path, sheet or None, name=file.filename or path.name)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        return output_format_body(result)

    @app.get("/output-format")
    def get_output_format() -> dict[str, Any]:
        return output_format_body(output_formats().get())

    @app.put("/output-format/mapping")
    def confirm_output_format(body: OutputMappingBody) -> dict[str, Any]:
        return output_format_body(output_formats().confirm(body.sources))

    @app.put("/output-format")
    def define_output_format(body: OutputColumnsBody) -> dict[str, Any]:
        columns = [
            (column.name, column.source, column.template_index, column.kind) for column in body.columns
        ]
        return output_format_body(output_formats().define(columns))

    @app.delete("/output-format", status_code=204)
    def delete_output_format() -> Response:
        output_formats().delete()
        return Response(status_code=204)

    @app.post("/sheets")
    def list_sheets(file: UploadFile = File(...)) -> dict[str, list[str]]:
        if reader is None:
            raise InvalidOperationError("spreadsheet reader is not configured")
        parent = None if dependencies.upload_dir is None else str(dependencies.upload_dir)
        directory = Path(tempfile.mkdtemp(prefix="pricor-sheets-", dir=parent))
        try:
            path = _store_upload(file, directory, dependencies.max_upload_bytes)
            names = reader.sheet_names(path)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        return {"sheets": names}

    @app.get("/suppliers")
    def list_suppliers() -> dict[str, list[str]]:
        if plans is None:
            return {"suppliers": []}
        return {"suppliers": list(plans.list_suppliers())}

    def memories() -> ManageMemory:
        if dependencies.memory is None:
            raise MemoryUnavailableError("semantic memory is not configured")
        return dependencies.memory

    @app.get("/memories")
    def list_memories() -> list[dict[str, Any]]:
        return [memory_body(item) for item in memories().list()]

    @app.post("/memories", status_code=201)
    def create_memory(
        body: MemoryNoteBody | AcceptedSuggestionMemoryBody,
    ) -> dict[str, Any]:
        manager = memories()
        if isinstance(body, MemoryNoteBody):
            created = manager.create_note(body.text, body.supplier_name)
        else:
            created = manager.create_accepted_suggestion(body.session_id, body.question_id)
        return memory_body(created)

    @app.patch("/memories/{memory_id}")
    def edit_memory(memory_id: str, body: EditMemoryBody) -> dict[str, Any]:
        return memory_body(memories().edit(memory_id, body.text))

    @app.delete("/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: str) -> Response:
        memories().delete(memory_id)
        return Response(status_code=204)

    @app.post("/imports", status_code=201)
    def create_import(
        file: UploadFile = File(...),
        supplier_name: str = Form(...),
        sheet: str | None = Form(None),
        language: str = Form("en"),
        force_first_import: bool = Form(False),
    ) -> dict[str, Any]:
        if language not in ("en", "es"):
            raise InvalidInputError("language must be 'en' or 'es'")
        parent = None if dependencies.upload_dir is None else str(dependencies.upload_dir)
        directory = Path(tempfile.mkdtemp(prefix="pricor-upload-", dir=parent))
        try:
            path = _store_upload(file, directory, dependencies.max_upload_bytes)
            session = use_case.start(
                path, supplier_name, sheet or None, language, force_first_import
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        return session_state(session)

    @app.get("/imports/{session_id}")
    def get_import(session_id: str) -> dict[str, Any]:
        return session_state(use_case.get(session_id))

    @app.put("/imports/{session_id}/header")
    def choose_header(session_id: str, body: HeaderBody) -> dict[str, Any]:
        return session_state(use_case.choose_header(session_id, body.row_index))

    @app.put("/imports/{session_id}/roles")
    def set_roles(session_id: str, body: RolesBody) -> dict[str, Any]:
        return session_state(use_case.set_roles(session_id, body.roles))

    @app.post("/imports/{session_id}/answers")
    def answer(session_id: str, body: AnswerBody) -> dict[str, Any]:
        return session_state(use_case.answer(session_id, body.question_id, body.option))

    @app.post("/imports/{session_id}/questions/{question_id}/ask")
    def ask_about_question(
        session_id: str, question_id: str, body: AskQuestionBody
    ) -> dict[str, str | None]:
        reply = question_help.execute(
            session_id,
            question_id,
            body.message,
            tuple(QuestionTurn(turn.role, turn.text) for turn in body.history),
        )
        return {"reply": reply.reply, "suggested_option": reply.suggested_option}

    @app.put("/imports/{session_id}/fx")
    def set_manual_rate(session_id: str, body: RateBody) -> dict[str, Any]:
        return session_state(use_case.set_manual_rate(session_id, body.rate))

    @app.post("/imports/{session_id}/fx/refresh")
    def refresh_rate(session_id: str) -> dict[str, Any]:
        return session_state(use_case.refresh_fx(session_id))

    @app.get("/imports/{session_id}/preview")
    def preview(
        session_id: str,
        offset: int = 0,
        limit: int = 50,
        q: str = "",
        status: str = "all",
    ) -> dict[str, Any]:
        return preview_body(use_case.preview(session_id, offset, limit, query=q, status=status))

    @app.get("/imports/{session_id}/sample")
    def sample(session_id: str, limit: int = 5) -> dict[str, Any]:
        return use_case.sample(session_id, limit)

    @app.post("/imports/{session_id}/approve")
    def approve(session_id: str) -> dict[str, Any]:
        return session_state(use_case.approve(session_id))

    @app.get("/imports/{session_id}/export")
    def export_products(session_id: str, format: str = "csv") -> Response:
        return _download(exports.products(session_id, format))

    @app.post("/imports/combined-export")
    def export_combined(body: CombinedExportBody) -> Response:
        return _download(exports.combined(body.session_ids, body.format, body.kind))

    @app.get("/imports/{session_id}/rejected")
    def export_rejected(session_id: str, format: str = "csv") -> Response:
        return _download(exports.rejected(session_id, format))

    def reporter() -> ReportPriceChanges:
        if dependencies.reports is None:
            raise InvalidOperationError("the price history is not available")
        return dependencies.reports

    @app.get("/imports/{session_id}/report")
    def price_report(session_id: str, threshold: str | None = None) -> dict[str, Any]:
        return report_body(reporter().compare(session_id, parse_threshold(threshold)))

    @app.get("/imports/{session_id}/report/export")
    def export_report(
        session_id: str, threshold: str | None = None, format: str = "csv"
    ) -> Response:
        if format != "csv":
            raise InvalidInputError(f"unknown format {format!r}; use: csv")
        return _download(reporter().export(session_id, parse_threshold(threshold)))

    @app.get("/samples")
    def list_samples() -> list[dict[str, Any]]:
        return [
            {
                "id": sample.id,
                "file_name": sample.file_name,
                "supplier_name": sample.supplier_name,
                "week": sample.week,
                "title": sample.title,
                "description": sample.description,
            }
            for sample in SAMPLES
        ]

    @app.get("/samples/{sample_id}")
    def get_sample_file(sample_id: str) -> Response:
        sample = find_sample(sample_id)
        if sample is None or not sample.path.is_file():
            return _error(404, "sample_not_found", f"no sample list {sample_id!r}")
        return Response(
            sample.path.read_bytes(),
            media_type=XLSX_CONTENT_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{sample.file_name}"'},
        )

    @app.post("/events", status_code=204)
    def record_event(body: Annotated[dict[str, Any], Body()]) -> Response:
        event = body.get("event")
        if not isinstance(event, str) or event not in EVENT_NAMES:
            raise InvalidInputError(f"unknown event; use one of: {', '.join(sorted(EVENT_NAMES))}")
        group = body.get("group")
        kept = group if isinstance(group, str) and _GROUP.fullmatch(group) else "-"
        events_logger.info("pricor_event event=%s group=%s", event, kept)
        return Response(status_code=204)

    @app.post("/warm-up")
    def warm_up_models() -> dict[str, str]:
        # Sync handler: runs in the threadpool, so waiting here never blocks the event loop. The
        # open request is what keeps Cloud Run's CPU allocated while the model loads.
        if warm_up is None:
            return {"models": "unavailable"}
        return {"models": warm_up.wait(dependencies.warm_up_timeout)}

    @app.get("/config")
    def get_config() -> dict[str, Any]:
        body: dict[str, Any] = {
            "model_provider": dependencies.model_provider,
            "demo": dependencies.demo,
            "workspaces": dependencies.workspaces,
        }
        if dependencies.google_client_id:
            body["google_client_id"] = dependencies.google_client_id
        return body

    if extra_routes is not None:
        extra_routes(app)
    if dependencies.web_dist is not None:
        install_web_app(app, dependencies.web_dist)
    return app
