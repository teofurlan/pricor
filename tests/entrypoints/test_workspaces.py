"""Private workspaces per visitor (S6, U6 contract in odd/tasks/render-deploy.md)."""

import hashlib
import logging
import re
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.entrypoints.workspaces import (
    COOKIE_NAME,
    OpenWorkspace,
    WorkspaceRegistry,
    create_workspace_app,
)

from ..application.fakes import FakeClassifier
from .test_api import ROLES, upload

TOKEN = re.compile(r"/w/([A-Za-z0-9_-]{43})$")


class RecordingBackup:
    """A `WorkspaceBackup` that keeps copies in memory and can be told to fail."""

    def __init__(self, fail: bool = False):
        self.saved: dict[str, bytes] = {}
        self.saves: list[str] = []
        self.restores: list[str] = []
        self.fail = fail

    def save(self, key: str, source: Path) -> None:
        self.saves.append(key)
        if self.fail:
            raise OSError("bucket unreachable")
        self.saved[key] = source.read_bytes()

    def restore(self, key: str, target: Path) -> bool:
        self.restores.append(key)
        if key not in self.saved:
            return False
        target.write_bytes(self.saved[key])
        return True


def opener(opened: list[Path] | None = None):
    def open_workspace(path: Path) -> OpenWorkspace:
        if opened is not None:
            opened.append(path)
        database = SqliteDatabase(path)
        use_case = ImportFirstTime(
            FileSpreadsheetReader(), database.sessions, [ClassifierStage("heuristics", FakeClassifier(ROLES))]
        )
        return OpenWorkspace(create_app(ApiDependencies(use_case)), database.close)

    return open_workspace


def public_dependencies() -> ApiDependencies:
    use_case = ImportFirstTime(FileSpreadsheetReader(), InMemoryImportSessionRepository(), [])
    return ApiDependencies(use_case, model_provider="gemini", demo=True)


def make_host(tmp_path, backup=None, max_open=16, opened=None, base_url="http://testserver"):
    backup = backup if backup is not None else RecordingBackup()
    registry = WorkspaceRegistry(tmp_path / "workspaces", opener(opened), backup, max_open=max_open)
    app = create_workspace_app(public_dependencies(), registry)
    return app, registry, backup


def client_for(app, base_url="http://testserver"):
    return TestClient(app, base_url=base_url, raise_server_exceptions=False)


def new_workspace(client) -> str:
    response = client.get("/workspace")
    assert response.status_code == 200
    match = TOKEN.search(response.json()["link"])
    assert match, response.json()
    return match.group(1)


def key_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# -- link and cookie --------------------------------------------------------------


def test_get_workspace_creates_one_and_returns_a_personal_link(tmp_path):
    app, _, _ = make_host(tmp_path)
    client = client_for(app)

    response = client.get("/workspace")

    assert response.status_code == 200
    assert set(response.json()) == {"link"}
    token = TOKEN.search(response.json()["link"]).group(1)
    assert response.json()["link"] == f"http://testserver/w/{token}"
    assert client.cookies.get(COOKIE_NAME) == token


def test_the_cookie_is_http_only_lax_for_a_year_and_not_secure_over_http(tmp_path):
    app, _, _ = make_host(tmp_path)

    header = client_for(app).get("/workspace").headers["set-cookie"]

    assert f"{COOKIE_NAME}=" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header or "SameSite=Lax" in header
    assert "Path=/" in header
    assert "Max-Age=31536000" in header
    assert "Secure" not in header


def test_the_cookie_is_secure_and_the_link_https_behind_an_https_proxy(tmp_path):
    app, _, _ = make_host(tmp_path)

    response = client_for(app).get("/workspace", headers={"X-Forwarded-Proto": "https"})

    assert "Secure" in response.headers["set-cookie"]
    assert response.json()["link"].startswith("https://testserver/w/")


def test_the_cookie_is_secure_over_https(tmp_path):
    app, _, _ = make_host(tmp_path)

    response = client_for(app, base_url="https://testserver").get("/workspace")

    assert "Secure" in response.headers["set-cookie"]


def test_get_workspace_keeps_the_existing_workspace(tmp_path):
    app, registry, _ = make_host(tmp_path)
    client = client_for(app)
    token = new_workspace(client)

    again = client.get("/workspace")

    assert again.json()["link"].endswith(f"/w/{token}")
    assert len(list((tmp_path / "workspaces").glob("*.sqlite"))) == 1


def test_the_personal_link_opens_the_same_workspace_from_another_device(tmp_path):
    app, _, _ = make_host(tmp_path)
    phone, laptop = client_for(app), client_for(app)
    token = new_workspace(phone)
    created = upload(phone)
    assert created.status_code == 201

    response = laptop.get(f"/w/{token}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert laptop.cookies.get(COOKIE_NAME) == token
    assert laptop.get(f"/imports/{created.json()['id']}").status_code == 200


@pytest.mark.parametrize("token", ["A" * 43, "short", "A" * 44, "A" * 42 + "!"])
def test_an_unknown_or_malformed_link_is_a_404(tmp_path, token):
    app, _, _ = make_host(tmp_path)
    client = client_for(app)

    response = client.get(f"/w/{token}", follow_redirects=False)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workspace_not_found"
    assert COOKIE_NAME not in client.cookies
    assert not (tmp_path / "workspaces").exists() or not list((tmp_path / "workspaces").iterdir())


# -- isolation and access ---------------------------------------------------------


def test_api_calls_without_a_workspace_are_a_401(tmp_path):
    app, _, _ = make_host(tmp_path)
    client = client_for(app)

    for response in (upload(client), client.get("/imports/abc"), client.get("/memories"),
                     client.get("/output-format")):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "workspace_required"


def test_a_forged_cookie_is_a_401_and_creates_nothing(tmp_path):
    app, _, _ = make_host(tmp_path)
    client = client_for(app)
    client.cookies.set(COOKIE_NAME, "B" * 43)

    response = upload(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "workspace_required"
    assert not (tmp_path / "workspaces").exists() or not list((tmp_path / "workspaces").iterdir())


def test_one_workspace_cannot_see_another_workspaces_imports(tmp_path):
    app, _, _ = make_host(tmp_path)
    alice, bob = client_for(app), client_for(app)
    new_workspace(alice)
    new_workspace(bob)

    created = upload(alice)
    assert created.status_code == 201

    assert alice.get(f"/imports/{created.json()['id']}").status_code == 200
    assert bob.get(f"/imports/{created.json()['id']}").status_code == 404


def test_public_paths_need_no_workspace(tmp_path):
    app, _, _ = make_host(tmp_path)
    client = client_for(app)

    assert client.get("/samples").status_code == 200
    config = client.get("/config")
    assert config.status_code == 200
    assert config.json() == {"model_provider": "gemini", "demo": True, "workspaces": True}
    assert COOKIE_NAME not in client.cookies


def test_files_are_named_by_the_token_hash_never_the_token(tmp_path):
    app, _, _ = make_host(tmp_path)
    token = new_workspace(client_for(app))

    names = [path.name for path in (tmp_path / "workspaces").iterdir()]

    assert f"{key_of(token)}.sqlite" in names
    assert not any(token in name for name in names)


def test_the_token_never_reaches_the_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    app, _, _ = make_host(tmp_path, backup=RecordingBackup(fail=True))
    client = client_for(app)
    token = new_workspace(client)
    upload(client)

    assert token not in caplog.text


# -- backup and restore -----------------------------------------------------------


def test_a_successful_change_is_backed_up_before_the_answer_and_a_read_is_not(tmp_path):
    app, _, backup = make_host(tmp_path)
    client = client_for(app)
    token = new_workspace(client)
    after_create = len(backup.saves)

    created = upload(client)
    assert created.status_code == 201
    assert backup.saves[after_create:] == [key_of(token)]
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(backup.saved[key_of(token)])
    with sqlite3.connect(copy) as connection:
        assert connection.execute("select count(*) from sessions").fetchone()[0] == 1

    client.get(f"/imports/{created.json()['id']}")
    assert len(backup.saves) == after_create + 1


def test_a_failed_change_is_not_backed_up(tmp_path):
    app, _, backup = make_host(tmp_path)
    client = client_for(app)
    new_workspace(client)
    before = len(backup.saves)

    response = upload(client, filename="lista.exe")

    assert response.status_code == 415
    assert len(backup.saves) == before


def test_a_failing_backup_is_logged_and_the_change_still_succeeds(tmp_path, caplog):
    app, _, backup = make_host(tmp_path, backup=RecordingBackup(fail=True))
    client = client_for(app)
    new_workspace(client)

    with caplog.at_level(logging.WARNING, logger="pricor"):
        response = upload(client)

    assert response.status_code == 201
    assert backup.saves
    assert any(record.levelno == logging.WARNING and "backup" in record.getMessage()
               for record in caplog.records)


def test_a_workspace_missing_locally_is_restored_from_the_backup(tmp_path):
    backup = RecordingBackup()
    first, _, _ = make_host(tmp_path / "before", backup=backup)
    client = client_for(first)
    token = new_workspace(client)
    created = upload(client)

    # A new instance with an empty disk, as after Cloud Run scales to zero.
    second, _, _ = make_host(tmp_path / "after", backup=backup)
    visitor = client_for(second)
    assert visitor.get(f"/w/{token}", follow_redirects=False).status_code == 303

    assert key_of(token) in backup.restores
    assert visitor.get(f"/imports/{created.json()['id']}").status_code == 200


def test_a_cookie_for_a_workspace_restored_from_backup_works_without_the_link(tmp_path):
    backup = RecordingBackup()
    first, _, _ = make_host(tmp_path / "before", backup=backup)
    client = client_for(first)
    token = new_workspace(client)
    created = upload(client)

    second, _, _ = make_host(tmp_path / "after", backup=backup)
    returning = client_for(second)
    returning.cookies.set(COOKIE_NAME, token)

    assert returning.get(f"/imports/{created.json()['id']}").status_code == 200


# -- registry bounds --------------------------------------------------------------


def test_least_recently_used_workspaces_are_closed_and_reopen_on_return(tmp_path):
    opened: list[Path] = []
    app, _, _ = make_host(tmp_path, max_open=1, opened=opened)
    alice, bob = client_for(app), client_for(app)
    new_workspace(alice)
    created = upload(alice)
    new_workspace(bob)
    upload(bob)

    assert alice.get(f"/imports/{created.json()['id']}").status_code == 200
    assert len(opened) == 3  # alice, bob, alice again after eviction


def test_concurrent_first_requests_open_a_workspace_once(tmp_path):
    opened: list[Path] = []
    gate = threading.Barrier(4)
    registry = WorkspaceRegistry(tmp_path / "w", opener(opened), RecordingBackup())
    token = registry.create()
    opened.clear()
    registry.close_all()
    results = []

    def visit():
        gate.wait()
        with registry.lease(token) as workspace:
            results.append(workspace is not None)

    threads = [threading.Thread(target=visit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [True] * 4
    assert len(opened) == 1
