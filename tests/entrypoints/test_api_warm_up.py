import logging
import threading

from fastapi.testclient import TestClient

from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository

from ..application.fakes import FakeClassifier
from .test_api import ROLES


def make_app(warm_up):
    use_case = ImportFirstTime(
        FileSpreadsheetReader(),
        InMemoryImportSessionRepository(),
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
        None,
    )
    return create_app(ApiDependencies(use_case, warm_up=warm_up))


def test_the_warm_up_runs_once_in_the_background_while_the_app_already_answers():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def warm_up():
        calls.append(threading.current_thread())
        started.set()
        release.wait(5)
        finished.set()

    with TestClient(make_app(warm_up)) as client:
        assert started.wait(5)
        assert client.get("/config").status_code == 200  # answered while the warm-up is blocked
        assert not finished.is_set()
        release.set()
        assert finished.wait(5)
        client.get("/config")

    assert len(calls) == 1
    assert calls[0] is not threading.main_thread()


def test_a_failing_warm_up_is_logged_and_never_stops_the_app(caplog):
    done = threading.Event()

    def warm_up():
        try:
            raise RuntimeError("no gpu today")
        finally:
            done.set()

    with caplog.at_level(logging.WARNING), TestClient(make_app(warm_up)) as client:
        assert done.wait(5)
        assert client.get("/config").status_code == 200

    assert any("warm-up" in r.getMessage() and "no gpu today" in r.getMessage() for r in caplog.records)


def test_without_a_warm_up_the_app_starts_as_before():
    with TestClient(make_app(None)) as client:
        assert client.get("/config").status_code == 200
