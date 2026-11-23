"""Private workspaces for the hosted demo: one SQLite database per visitor.

A visitor gets a random token, kept in an HttpOnly cookie and shown as a personal link
(`/#w=<token>`, the token in the URL fragment so it never reaches a server log) to come back from another device. Requests to the data paths (imports,
memories, output format, sheets) go to that visitor's own app over its own database; the
configuration, the sample lists and the web shell are public. The models are built once and
shared by every workspace (see `wiring.workspace_app_from_env`).

The token is a bearer secret: files and backups are named by its SHA-256, and it is never
logged. After every successful change the database is copied to the `WorkspaceBackup` before
the answer completes, so a server that restarts with an empty disk restores it on return.
"""

import hashlib
import logging
import re
import secrets
import sqlite3
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.entrypoints.workspace_accounts import WorkspaceAccountStore
from pricor.ports.google_auth import GoogleTokenVerifier, InvalidGoogleTokenError
from pricor.ports.workspace_backup import WorkspaceBackup

logger = logging.getLogger(__name__)

COOKIE_NAME = "pricor_workspace"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60
DEFAULT_MAX_OPEN = 16
# First path segments that hold a visitor's data; everything else is public.
WORKSPACE_PREFIXES = frozenset({"imports", "memories", "output-format", "sheets"})
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_READS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class OpenWorkspace:
    app: ASGIApp
    close: Callable[[], None]


@dataclass
class _Entry:
    workspace: OpenWorkspace
    users: int = 0
    saving: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class Lease:
    key: str
    workspace: OpenWorkspace


def is_valid_token(token: str | None) -> bool:
    return token is not None and _TOKEN.fullmatch(token) is not None


def workspace_key(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class WorkspaceRegistry:
    """Opens workspaces on demand, keeps at most `max_open` idle ones, and backs them up."""

    def __init__(
        self,
        directory: Path,
        open_workspace: Callable[[Path], OpenWorkspace],
        backup: WorkspaceBackup,
        max_open: int = DEFAULT_MAX_OPEN,
    ):
        if max_open < 1:
            raise ValueError("max_open must be at least 1")
        self._directory = Path(directory)
        self._open_workspace = open_workspace
        self._backup = backup
        self._max_open = max_open
        self._lock = threading.Lock()
        self._open: OrderedDict[str, _Entry] = OrderedDict()
        self._restoring: dict[str, threading.Lock] = {}

    def _path(self, key: str) -> Path:
        return self._directory / f"{key}.sqlite"

    def create(self) -> str:
        """A new empty workspace, backed up at once so its link survives a restart."""
        token = secrets.token_urlsafe(32)
        lease = self._acquire(token, create=True)
        assert lease is not None  # a new token always opens
        try:
            self.backup_quietly(lease)
        finally:
            self.release(lease)
        return token

    def exists(self, token: str | None) -> bool:
        lease = self.acquire(token)
        if lease is None:
            return False
        self.release(lease)
        return True

    def is_empty(self, token: str | None) -> bool:
        lease = self.acquire(token)
        if lease is None:
            return True
        try:
            path = self._path(lease.key)
            if not path.is_file():
                return True
            with closing(sqlite3.connect(path)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                for table in ("sessions", "plans", "memories", "output_format"):
                    if table in tables:
                        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        if count > 0:
                            return False
            return True
        finally:
            self.release(lease)

    @contextmanager
    def lease(self, token: str | None) -> Iterator[OpenWorkspace | None]:
        """The open workspace for `token` while the block runs (never closed meanwhile), or None."""
        held = self.acquire(token)
        try:
            yield held.workspace if held is not None else None
        finally:
            if held is not None:
                self.release(held)

    def acquire(self, token: str | None) -> Lease | None:
        """The open workspace for `token` (restored from the backup if needed), or None."""
        if not is_valid_token(token):
            return None
        return self._acquire(token, create=False)

    def _acquire(self, token: str, *, create: bool) -> Lease | None:
        key = workspace_key(token)
        with self._lock:
            entry = self._open.get(key)
            if entry is not None:
                self._open.move_to_end(key)
                entry.users += 1
                self._evict_idle()
                return Lease(key, entry.workspace)
            path = self._path(key)
            self._directory.mkdir(parents=True, exist_ok=True)
            if create or path.is_file():
                entry = _Entry(self._open_workspace(path))
                self._open[key] = entry
                self._open.move_to_end(key)
                entry.users += 1
                self._evict_idle()
                return Lease(key, entry.workspace)
            restore_lock = self._restoring.setdefault(key, threading.Lock())

        with restore_lock:
            with self._lock:
                entry = self._open.get(key)
                if entry is not None:
                    self._open.move_to_end(key)
                    entry.users += 1
                    self._evict_idle()
                    return Lease(key, entry.workspace)
            restored = path.is_file() or self._restore(key, path)
            with self._lock:
                self._restoring.pop(key, None)
                if not restored:
                    return None
                entry = self._open.get(key)
                if entry is None:
                    entry = _Entry(self._open_workspace(path))
                    self._open[key] = entry
                self._open.move_to_end(key)
                entry.users += 1
                self._evict_idle()
                return Lease(key, entry.workspace)

    def _restore(self, key: str, path: Path) -> bool:
        try:
            restored = self._backup.restore(key, path)
        except Exception as error:
            logger.warning("workspace restore failed (%s)", type(error).__name__)
            restored = False
        if not restored:
            path.unlink(missing_ok=True)
        return restored and path.is_file()

    def release(self, lease: Lease) -> None:
        with self._lock:
            entry = self._open.get(lease.key)
            if entry is not None:
                entry.users -= 1
            self._evict_idle()

    def _evict_idle(self) -> None:
        for key in list(self._open):
            if len(self._open) <= self._max_open:
                return
            entry = self._open[key]
            if entry.users == 0:
                del self._open[key]
                entry.workspace.close()

    def save(self, lease: Lease) -> None:
        """Copy the workspace database (SQLite backup API) and hand the copy to the backup."""
        with self._lock:
            entry = self._open.get(lease.key)
        saving = entry.saving if entry is not None else threading.Lock()
        with saving, tempfile.TemporaryDirectory(dir=self._directory) as scratch:
            copy = Path(scratch) / "copy.sqlite"
            source = sqlite3.connect(self._path(lease.key))
            target = sqlite3.connect(copy)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            self._backup.save(lease.key, copy)

    def backup_quietly(self, lease: Lease) -> None:
        try:
            self.save(lease)
        except Exception as error:
            logger.warning(
                "workspace backup failed (%s); the change is kept on this server only",
                type(error).__name__,
            )

    def close_all(self) -> None:
        with self._lock:
            entries = list(self._open.values())
            self._open.clear()
        for entry in entries:
            entry.workspace.close()


def _scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return forwarded or request.url.scheme


def _with_cookie(response: Response, token: str, request: Request) -> Response:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_scheme(request) == "https",
    )
    return response


def _not_found() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "workspace_not_found", "message": "this workspace link does not exist"}},
        status_code=404,
    )


def _workspace_required() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "workspace_required",
                "message": "open the app first to get a private workspace",
            }
        },
        status_code=401,
    )


def _unsupported_media_type() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "unsupported_media_type",
                "message": "send the token as a JSON body (Content-Type: application/json)",
            }
        },
        status_code=415,
    )


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _link(request: Request, token: str) -> str:
    host = request.headers.get("host") or request.url.netloc
    return f"{_scheme(request)}://{host}/#w={token}"


def _is_json(request: Request) -> bool:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return media_type == "application/json"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


def _workspace_body(
    request: Request, token: str, accounts: WorkspaceAccountStore | None
) -> dict[str, Any]:
    body: dict[str, Any] = {"link": _link(request, token)}
    if accounts is not None:
        linked = accounts.get_by_workspace_key(workspace_key(token))
        if linked is not None:
            body["account"] = {"email": linked.email}
    return body


def install_workspace_routes(
    app: FastAPI,
    registry: WorkspaceRegistry,
    accounts: WorkspaceAccountStore | None = None,
    google_verifier: GoogleTokenVerifier | None = None,
) -> None:
    @app.get("/workspace")
    def workspace(request: Request) -> Response:
        token = request.cookies.get(COOKIE_NAME)
        if not registry.exists(token):
            token = registry.create()
        assert token is not None
        response = JSONResponse(_workspace_body(request, token, accounts))
        return _no_store(_with_cookie(response, token, request))

    @app.get("/workspace/current")
    def current(request: Request) -> Response:
        token = request.cookies.get(COOKIE_NAME)
        if token is None or not registry.exists(token):
            return _no_store(_not_found())
        return _no_store(JSONResponse(_workspace_body(request, token, accounts)))

    @app.post("/workspace/claim")
    async def claim(request: Request) -> Response:
        # JSON only: a cross-site form or text/plain POST is refused here, and a cross-site
        # application/json POST needs a CORS preflight that this app never grants.
        if not _is_json(request):
            return _no_store(_unsupported_media_type())
        try:
            body = await request.json()
        except ValueError:
            body = None
        token = body.get("token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not await run_in_threadpool(registry.exists, token):
            return _no_store(_not_found())
        payload = await run_in_threadpool(_workspace_body, request, token, accounts)
        response = JSONResponse(payload)
        return _no_store(_with_cookie(response, token, request))

    @app.post("/workspace/google")
    async def google_sign_in(request: Request) -> Response:
        if not _is_json(request):
            return _no_store(_unsupported_media_type())
        if google_verifier is None or accounts is None:
            return _no_store(
                _error_response(
                    404,
                    "google_auth_unavailable",
                    "Google sign-in is not configured on this server",
                )
            )
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return _no_store(_error_response(422, "invalid_input", "expected a JSON object"))
        credential = body.get("credential")
        if not isinstance(credential, str) or not credential.strip():
            return _no_store(
                _error_response(422, "invalid_input", "credential must be a non-empty string")
            )
        resolution = body.get("resolution", "auto")
        if resolution not in ("auto", "use_account", "link_current"):
            return _no_store(
                _error_response(
                    422,
                    "invalid_input",
                    "resolution must be 'auto', 'use_account', or 'link_current'",
                )
            )
        try:
            identity = await run_in_threadpool(google_verifier.verify, credential)
        except InvalidGoogleTokenError as err:
            return _no_store(_error_response(401, "invalid_google_token", str(err)))

        existing = await run_in_threadpool(accounts.get_by_sub, identity.sub)
        if existing is not None and await run_in_threadpool(registry.exists, existing.token):
            account_token: str | None = existing.token
        else:
            account_token = None

        current_token = request.cookies.get(COOKIE_NAME)
        has_current = await run_in_threadpool(registry.exists, current_token)

        if account_token is None or account_token == current_token or resolution == "link_current":
            if not has_current:
                current_token = await run_in_threadpool(registry.create)
            assert current_token is not None
            await run_in_threadpool(accounts.link, identity.sub, identity.email, current_token)
            response = JSONResponse(
                {
                    "status": "linked",
                    "link": _link(request, current_token),
                    "account": {"email": identity.email},
                }
            )
            return _no_store(_with_cookie(response, current_token, request))

        if (
            resolution == "use_account"
            or not has_current
            or await run_in_threadpool(registry.is_empty, current_token)
        ):
            response = JSONResponse(
                {
                    "status": "switched",
                    "link": _link(request, account_token),
                    "account": {"email": identity.email},
                }
            )
            return _no_store(_with_cookie(response, account_token, request))

        assert current_token is not None
        return _no_store(
            JSONResponse(
                {
                    "status": "conflict",
                    "link": _link(request, current_token),
                    "account": {"email": identity.email},
                }
            )
        )

    @app.delete("/workspace/google")
    async def unlink_google(request: Request) -> Response:
        current_token = request.cookies.get(COOKIE_NAME)
        if not current_token or not await run_in_threadpool(registry.exists, current_token):
            return _no_store(_workspace_required())
        if accounts is not None:
            await run_in_threadpool(
                accounts.unlink_by_workspace_key, workspace_key(current_token)
            )
        return _no_store(JSONResponse({"link": _link(request, current_token), "account": None}))


class WorkspaceDispatcher:
    """Sends data paths to the visitor's workspace app and everything else to the public app."""

    def __init__(self, public: ASGIApp, registry: WorkspaceRegistry):
        self.public = public
        self.registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].lstrip("/").split("/", 1)[0] not in WORKSPACE_PREFIXES:
            await self.public(scope, receive, send)
            return
        token = Request(scope).cookies.get(COOKIE_NAME)
        lease = await run_in_threadpool(self.registry.acquire, token)
        if lease is None:
            await _workspace_required()(scope, receive, send)
            return
        changes = scope["method"] not in _READS
        state: dict[str, Any] = {"status": 0, "saved": False}

        async def relay(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            elif (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and changes
                and 200 <= state["status"] < 300
                and not state["saved"]
            ):
                state["saved"] = True
                await run_in_threadpool(self.registry.backup_quietly, lease)
            await send(message)

        try:
            await lease.workspace.app(scope, receive, relay)
        finally:
            # Synchronous on purpose: an awaited release would be skipped when the request is
            # cancelled, pinning the workspace open forever. It only takes a short lock.
            self.registry.release(lease)


def create_workspace_app(
    public: ApiDependencies,
    registry: WorkspaceRegistry,
    accounts: WorkspaceAccountStore | None = None,
    google_verifier: GoogleTokenVerifier | None = None,
) -> ASGIApp:
    """The public app (config, samples, web shell, workspace links) in front of the workspaces."""
    app = create_app(
        replace(public, workspaces=True),
        extra_routes=lambda app: install_workspace_routes(app, registry, accounts, google_verifier),
    )
    return WorkspaceDispatcher(app, registry)
