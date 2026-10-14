from datetime import UTC, datetime
from itertools import count

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.ports.import_session import SessionStatus

from .sessions import Flow

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def database(tmp_path):
    database = SqliteDatabase(tmp_path / "pricor.db")
    yield database
    database.close()


def flow_for(database, supplier="Ferreteria Ejemplo"):
    ids = (f"s{n}" for n in count(1))
    return Flow(
        database.sessions,
        supplier=supplier,
        approvals=database,
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )


class Boom(Exception):
    pass


class FailingHistory:
    def record_import(self, *args, **kwargs):
        raise Boom("disk full")


class FailingPlans:
    def save(self, *args, **kwargs):
        raise Boom("disk full")


def test_approval_stores_plan_history_and_session_together(database):
    flow = flow_for(database)
    session = flow.approved()

    stored = database.plans.latest_for("Ferreteria Ejemplo")
    assert stored.version == 1
    assert stored.plan == session.approved_plan
    assert stored.created_at == NOW
    assert stored.fingerprint.sheet_name == "Hoja1"
    assert stored.fingerprint.header_row == session.profile.header_row
    assert [(c.index, c.header, c.apparent_type) for c in stored.fingerprint.columns] == [
        (c.index, c.header, c.apparent_type.value) for c in session.profile.columns
    ]

    (summary,) = database.history.imports_for("Ferreteria Ejemplo")
    assert summary.import_id == session.id
    assert summary.imported_at == NOW
    records = database.history.records_of(session.id)
    assert [(item.row_number, item.record) for item in records] == [
        (row.row_number, row.record) for row in session.approved_result.accepted
    ]
    assert database.sessions.get(session.id).status is SessionStatus.APPROVED


def test_a_failure_while_storing_history_leaves_nothing_behind(database):
    flow = flow_for(database)
    session = flow.ready()
    real_history = database.history
    database.history = FailingHistory()

    with pytest.raises(Boom):
        flow.use_case.approve(session.id)

    database.history = real_history
    assert database.plans.latest_for("Ferreteria Ejemplo") is None
    assert database.history.imports_for("Ferreteria Ejemplo") == ()
    assert database.sessions.get(session.id).status is SessionStatus.READY_FOR_PREVIEW

    approved = flow.use_case.approve(session.id)  # the user can simply try again
    assert approved.status is SessionStatus.APPROVED
    assert database.plans.latest_for("Ferreteria Ejemplo").version == 1


def test_a_failure_while_storing_the_plan_leaves_nothing_behind(database):
    flow = flow_for(database)
    session = flow.ready()
    real_plans = database.plans
    database.plans = FailingPlans()

    with pytest.raises(Boom):
        flow.use_case.approve(session.id)

    database.plans = real_plans
    assert database.history.imports_for("Ferreteria Ejemplo") == ()
    assert database.sessions.get(session.id).approved is False


def test_a_failed_approval_does_not_freeze_a_live_in_memory_session(database):
    # The use case may be handed repositories that return live objects.
    from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository

    memory = InMemoryImportSessionRepository()
    flow = Flow(memory, approvals=database, clock=lambda: NOW)
    session = flow.ready()
    database.history = FailingHistory()

    with pytest.raises(Boom):
        flow.use_case.approve(session.id)

    live = memory.get(session.id)
    assert live.approved is False
    assert live.approved_plan is None and live.approved_result is None
    assert live.status is SessionStatus.READY_FOR_PREVIEW


def test_approving_twice_does_not_duplicate_anything(database):
    flow = flow_for(database)
    session = flow.approved()
    flow.use_case.approve(session.id)
    assert len(database.plans.versions_for("Ferreteria Ejemplo")) == 1
    assert len(database.history.imports_for("Ferreteria Ejemplo")) == 1


def test_a_second_import_of_the_supplier_adds_a_plan_version_and_an_import(database):
    flow = flow_for(database)
    first = flow.approved()
    second = flow.approved()
    assert first.id != second.id
    assert [v.version for v in database.plans.versions_for("ferreteria ejemplo")] == [1, 2]
    assert [s.import_id for s in database.history.imports_for("Ferreteria Ejemplo")] == [first.id, second.id]


def test_without_a_unit_of_work_approval_still_works():
    flow = Flow()
    assert flow.approved().status is SessionStatus.APPROVED
