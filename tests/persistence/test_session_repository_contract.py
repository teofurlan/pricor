"""One contract, every adapter: sessions must come back exactly as they were saved."""

import pytest

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session import SessionStatus
from pricor.ports.import_session_repository import SessionNotFoundError
from pricor.ports.plan_advisor import ParameterId

from .sessions import Flow


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        yield InMemoryImportSessionRepository()
        return
    database = SqliteDatabase(tmp_path / "pricor.db")
    yield database.sessions
    database.close()


def test_get_returns_what_the_use_case_added(repository):
    flow = Flow(repository)
    session = flow.start()
    loaded = repository.get(session.id)
    assert loaded == session
    assert repr(loaded) == repr(session)


def test_unknown_sessions_are_reported(repository):
    with pytest.raises(SessionNotFoundError):
        repository.get("missing")
    flow = Flow()
    with pytest.raises(SessionNotFoundError):
        repository.save(flow.start())


def test_saved_changes_are_visible_to_the_next_get(repository):
    flow = Flow(repository)
    session = flow.start()
    flow.use_case.set_roles(session.id, {0: R.CODE})
    flow.use_case.answer(session.id, "currency", "USD")
    loaded = repository.get(session.id)
    assert loaded.decisions[0].decided_by == "user"
    assert loaded.answers == {ParameterId.CURRENCY: "USD"}
    assert loaded == flow.use_case.get(session.id)


def test_a_full_flow_to_approval_survives_every_step(repository):
    flow = Flow(repository)
    approved = flow.approved()
    loaded = repository.get(approved.id)
    assert loaded.status is SessionStatus.APPROVED
    assert loaded.approved_result == approved.approved_result
    assert loaded.approved_plan == approved.approved_plan
    assert repr(loaded.approved_result) == repr(approved.approved_result)
    preview = flow.use_case.preview(approved.id)
    assert preview.totals["accepted"] == len(approved.approved_result.accepted)


def test_sessions_are_independent(repository):
    flow = Flow(repository)
    first, second = flow.start(), flow.headerless()
    assert repository.get(first.id).supplier_name != repository.get(second.id).supplier_name


def test_sqlite_sessions_survive_reopening_the_file(tmp_path):
    path = tmp_path / "pricor.db"
    database = SqliteDatabase(path)
    session = Flow(database.sessions).ready()
    database.close()

    reopened = SqliteDatabase(path)
    try:
        loaded = reopened.sessions.get(session.id)
        assert loaded == session
        assert repr(loaded) == repr(session)
    finally:
        reopened.close()
