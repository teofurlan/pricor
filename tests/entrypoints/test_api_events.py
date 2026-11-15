import logging

import pytest
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app

from .test_workspaces import client_for, make_host


def make_client() -> TestClient:
    use_case = ImportFirstTime(FileSpreadsheetReader(), InMemoryImportSessionRepository(), [])
    return TestClient(create_app(ApiDependencies(use_case)))


def event_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "pricor.events"]


def test_event_answers_204_without_body_and_logs_one_line(caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")

    response = make_client().post("/events", json={"event": "approved", "group": "grupo-1"})

    assert response.status_code == 204
    assert response.content == b""
    assert event_lines(caplog) == ["pricor_event event=approved group=grupo-1"]
    assert [r.levelno for r in caplog.records if r.name == "pricor.events"] == [logging.INFO]


@pytest.mark.parametrize("event", ["visit", "import_started", "approved", "downloaded"])
def test_every_known_event_is_accepted(event, caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")

    assert make_client().post("/events", json={"event": event, "group": None}).status_code == 204
    assert event_lines(caplog) == [f"pricor_event event={event} group=-"]


def test_unknown_event_is_422_invalid_input_and_not_logged(caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")

    response = make_client().post("/events", json={"event": "login", "group": "a"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert event_lines(caplog) == []


@pytest.mark.parametrize("group", ["a1_b-c", "x" * 40])
def test_valid_group_is_kept(group, caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")

    make_client().post("/events", json={"event": "visit", "group": group})

    assert event_lines(caplog) == [f"pricor_event event=visit group={group}"]


@pytest.mark.parametrize("group", ["Grupo", "a b", "x" * 41, "", "a\nb", "a;b", 7, None])
def test_invalid_or_missing_group_is_recorded_as_dash(group, caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")

    assert make_client().post("/events", json={"event": "visit", "group": group}).status_code == 204
    assert event_lines(caplog) == ["pricor_event event=visit group=-"]


def test_group_may_be_omitted(caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")

    assert make_client().post("/events", json={"event": "visit"}).status_code == 204
    assert event_lines(caplog) == ["pricor_event event=visit group=-"]


def test_nothing_else_is_logged(caplog):
    caplog.set_level(logging.INFO)

    make_client().post(
        "/events",
        json={"event": "visit", "group": "g1", "ip": "1.2.3.4", "supplier": "Acme"},
        headers={"User-Agent": "SecretAgent/9", "Cookie": "pricor_workspace=tok"},
    )

    text = " ".join(r.getMessage() for r in caplog.records if r.name == "pricor.events")
    assert text == "pricor_event event=visit group=g1"
    for leaked in ("SecretAgent", "1.2.3.4", "Acme", "tok", "testclient"):
        assert leaked not in text


def test_events_need_no_workspace_and_create_none(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="pricor.events")
    app, _, _ = make_host(tmp_path)

    response = client_for(app).post("/events", json={"event": "visit", "group": "g1"})

    assert response.status_code == 204
    assert event_lines(caplog) == ["pricor_event event=visit group=g1"]
    assert not list((tmp_path / "workspaces").glob("*"))
