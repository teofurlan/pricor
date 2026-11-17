import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app

from .test_workspaces import client_for, make_host


def make_client(warm_up, timeout=5.0) -> TestClient:
    use_case = ImportFirstTime(FileSpreadsheetReader(), InMemoryImportSessionRepository(), [])
    return TestClient(create_app(ApiDependencies(use_case, warm_up=warm_up, warm_up_timeout=timeout)))


def test_answers_ready_once_the_warm_up_has_finished():
    response = make_client(lambda: None).post("/warm-up")

    assert response.status_code == 200
    assert response.json() == {"models": "ready"}


def test_answers_loading_when_the_warm_up_outlasts_the_timeout():
    release = threading.Event()
    client = make_client(lambda: release.wait(5), timeout=0.05)

    response = client.post("/warm-up")
    release.set()

    assert response.status_code == 200
    assert response.json() == {"models": "loading"}


def test_answers_unavailable_without_a_warm_up():
    response = make_client(None).post("/warm-up")

    assert response.status_code == 200
    assert response.json() == {"models": "unavailable"}


def test_answers_unavailable_not_5xx_when_the_warm_up_raises():
    def boom():
        raise RuntimeError("no model")

    response = make_client(boom).post("/warm-up")

    assert response.status_code == 200
    assert response.json() == {"models": "unavailable"}


def test_concurrent_calls_trigger_a_single_load():
    loads = []
    release = threading.Event()

    def warm_up():
        loads.append(1)
        release.wait(5)

    client = make_client(warm_up)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, "/warm-up") for _ in range(2)]
        time.sleep(0.2)
        release.set()
        bodies = [future.result().json() for future in futures]

    assert bodies == [{"models": "ready"}, {"models": "ready"}]
    assert len(loads) == 1


def test_a_call_after_the_startup_warm_up_does_not_load_again():
    loads = []
    with TestClient(create_app(ApiDependencies(
        ImportFirstTime(FileSpreadsheetReader(), InMemoryImportSessionRepository(), []),
        warm_up=lambda: loads.append(1),
    ))) as client:
        assert client.post("/warm-up").json() == {"models": "ready"}
        assert client.post("/warm-up").json() == {"models": "ready"}

    assert len(loads) == 1


def test_needs_no_workspace_cookie_and_creates_no_workspace(tmp_path):
    app, _, _ = make_host(tmp_path)

    response = client_for(app).post("/warm-up")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert not list((tmp_path / "workspaces").glob("*"))
