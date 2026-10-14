"""Reusing a supplier's saved plan for its next file.

The first approval goes through the real SQLite store (in memory) so the saved plan and
fingerprint are exactly what a second import would find.
"""

from datetime import UTC, datetime
from itertools import count

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.reuse_supplier_plan import SAVED_PLAN, ReuseSupplierPlan
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session import SessionStatus

from .fakes import FakeClassifier, FakeReader

ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Precio lista": (R.COST_PRICE, 0.9),
    "IVA": (R.VAT_RATE, 0.9),
    "Dto": (R.DISCOUNT, 0.9),
    "Notas": (R.IGNORE, 0.9),
}
FIRST = [
    ["Codigo", "Descripcion", "Precio lista", "IVA"],
    ["A1", "Tornillo", "1.210,00", "21%"],
    ["A2", "Tuerca", "968,00", "21%"],
    ["A3", "Arandela", "121,00", "21%"],
    ["A4", "Clavo", "60,50", "21%"],
]
SECOND = [
    ["Codigo", "Descripcion", "Precio lista", "IVA"],
    ["A1", "Tornillo", "1.331,00", "21%"],
    ["A2", "Tuerca", "968,00", "21%"],
    ["A3", "Arandela", "133,10", "21%"],
    ["A4", "Clavo", "60,50", "21%"],
    ["A5", "Taco", "1.815,00", "21%"],
]
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Harness:
    def __init__(self, table=ROLES, clock=lambda: NOW):
        self.reader = FakeReader(FIRST)
        self.classifier = FakeClassifier(table)
        self.database = SqliteDatabase(":memory:")
        ids = (f"s{n}" for n in count(1))
        self.use_case = ReuseSupplierPlan(
            self.reader,
            self.database.sessions,
            [ClassifierStage("heuristics", self.classifier)],
            plans=self.database.plans,
            approvals=self.database,
            clock=clock,
            id_factory=lambda: next(ids),
        )

    def start(self, rows, **kwargs):
        self.reader.rows = tuple(tuple(row) for row in rows)
        self.classifier.seen_indexes.clear()
        return self.use_case.start("lista.xlsx", "Ferreteria Ejemplo", **kwargs)

    def answer(self, session, **answers):
        for question_id, option in answers.items():
            self.use_case.answer(session.id, question_id, option)
        return self.use_case.get(session.id)

    def first_import(self, rows=FIRST):
        session = self.start(rows)
        assert session.mode == "first_import"
        session = self.answer(session, price_includes_vat="yes", currency="ARS")
        assert session.status is SessionStatus.READY_FOR_PREVIEW
        return self.use_case.approve(session.id)


@pytest.fixture
def harness():
    harness = Harness()
    yield harness
    harness.database.close()


def decided_by(session):
    return {column.header: column.decided_by for column in session.columns}


def change_kinds(session):
    return [(change.kind, change.header) for change in session.changes]


# -- a first import is unaffected --


def test_a_supplier_without_a_saved_plan_starts_a_first_import(harness):
    session = harness.start(FIRST)

    assert session.mode == "first_import"
    assert session.based_on_plan_version is None
    assert session.changes == ()
    assert set(decided_by(session).values()) == {"heuristics"}


# -- nothing changed --


def test_an_unchanged_file_goes_straight_to_preview_with_zero_questions(harness):
    harness.first_import()

    session = harness.start(SECOND)

    assert session.mode == "reuse"
    assert session.based_on_plan_version == 1
    assert session.changes == ()
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.questions == ()
    assert set(decided_by(session).values()) == {SAVED_PLAN}
    assert harness.classifier.seen_indexes == []  # no column went through the cascade


def test_reused_roles_and_confirmed_answers_carry_over_to_the_plan(harness):
    harness.first_import()

    session = harness.start(SECOND)

    assert {key.value: token for key, token in session.answers.items()} == {
        "price_includes_vat": "yes",
        "currency": "ARS",
    }
    page = harness.use_case.preview(session.id)
    assert page.totals["accepted"] == 5
    assert page.items[0].record["unit_cost_net"] == "1100.00"  # 1331 / 1.21


def test_approving_a_reused_import_saves_a_new_plan_version_and_the_price_history(harness):
    harness.first_import()
    session = harness.start(SECOND)

    harness.use_case.approve(session.id)

    versions = harness.database.plans.versions_for("Ferreteria Ejemplo")
    assert [stored.version for stored in versions] == [1, 2]
    assert versions[1].plan.steps == versions[0].plan.steps
    imports = harness.database.history.imports_for("Ferreteria Ejemplo")
    assert [item.import_id for item in imports] == ["s1", session.id]
    assert imports[1].record_count == 5


def test_a_plan_reused_twice_is_based_on_the_latest_version(harness):
    harness.first_import()
    harness.use_case.approve(harness.start(SECOND).id)

    session = harness.start(SECOND)

    assert session.based_on_plan_version == 2


# -- moved columns --


def test_a_moved_column_is_remapped_automatically_and_listed_as_a_change(harness):
    harness.first_import()
    reordered = [[row[2], row[0], row[1], row[3]] for row in SECOND]

    session = harness.start(reordered)

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.questions == ()
    moved = [change for change in session.changes if change.kind == "moved"]
    assert [(c.header, c.old_index, c.new_index, c.role) for c in moved] == [
        ("codigo", 0, 1, "code"),
        ("descripcion", 1, 2, "description"),
        ("precio lista", 2, 0, "cost_price"),
    ]
    assert {c.role: c.index for c in session.columns if c.role} == {
        R.CODE: 1,
        R.DESCRIPTION: 2,
        R.COST_PRICE: 0,
        R.VAT_RATE: 3,
    }
    assert harness.classifier.seen_indexes == []
    first = harness.use_case.preview(session.id).items[0]
    assert first.record["supplier_code"] == "A1"
    assert first.record["unit_cost_net"] == "1100.00"


# -- new columns --


def test_a_new_column_is_the_only_one_that_goes_through_the_cascade(harness):
    harness.first_import()
    wider = [[*row, "Stock" if n == 0 else "5"] for n, row in enumerate(SECOND)]

    session = harness.start(wider)

    assert harness.classifier.seen_indexes == [[4]]
    assert change_kinds(session) == [("new", "stock")]
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED
    stock = next(column for column in session.columns if column.header == "Stock")
    assert stock.role is None
    kept = {column.header: column.decided_by for column in session.columns if column.index < 4}
    assert set(kept.values()) == {SAVED_PLAN}

    session = harness.use_case.set_roles(session.id, {4: R.IGNORE})

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.questions == ()


def test_a_new_column_the_cascade_is_sure_about_keeps_its_stage(harness):
    table = {**ROLES, "Stock": (R.IGNORE, 0.9)}
    harness = Harness(table)
    harness.first_import()
    wider = [[*row, "Stock" if n == 0 else "5"] for n, row in enumerate(SECOND)]

    session = harness.start(wider)

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    stock = next(column for column in session.columns if column.header == "Stock")
    assert (stock.role, stock.decided_by) == (R.IGNORE, "heuristics")
    harness.database.close()


# -- retyped columns --


def test_a_retyped_column_is_classified_again_while_the_rest_is_kept(harness):
    harness.first_import()
    quoted = [
        SECOND[0],
        *[[row[0], row[1], "consultar", row[3]] for row in SECOND[1:]],
    ]

    session = harness.start(quoted)

    assert harness.classifier.seen_indexes == [[2]]
    assert [(c.kind, c.old_type, c.new_type) for c in session.changes] == [
        ("retyped", "decimal", "text")
    ]
    precio = next(column for column in session.columns if column.index == 2)
    assert precio.decided_by == "heuristics"
    assert decided_by(session)["Codigo"] == SAVED_PLAN


# -- missing columns --


def test_a_missing_vat_column_turns_the_vat_rule_into_a_question(harness):
    harness.first_import()
    without_vat = [row[:3] for row in SECOND]

    session = harness.start(without_vat)

    assert [(c.kind, c.header, c.used_by_plan, c.role) for c in session.changes] == [
        ("missing", "iva", True, "vat_rate")
    ]
    assert session.status is SessionStatus.QUESTIONS_PENDING
    assert [question.id.value for question in session.questions] == ["vat_rate"]
    assert harness.classifier.seen_indexes == []

    session = harness.answer(session, vat_rate="constant:21")

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert harness.use_case.preview(session.id).items[0].record["unit_cost_net"] == "1100.00"


def test_a_missing_discount_column_is_never_silently_dropped(harness):
    discounted = [[*row, "Dto" if n == 0 else "10"] for n, row in enumerate(FIRST)]
    harness.first_import(discounted)
    without_discount = [row[:4] for row in SECOND]

    session = harness.start(without_discount)

    assert [(c.kind, c.header, c.used_by_plan, c.role) for c in session.changes] == [
        ("missing", "dto", True, "discount")
    ]
    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED
    assert any("dto" in issue.lower() for issue in session.role_issues)
    assert session.plan is None

    with_other = [[*row, "Dto" if n == 0 else "5"] for n, row in enumerate(SECOND)]
    again = harness.start(with_other)
    assert again.status is SessionStatus.READY_FOR_PREVIEW


def test_a_missing_column_the_plan_never_used_is_only_listed(harness):
    wide = [[*row, "Notas" if n == 0 else "x"] for n, row in enumerate(FIRST)]
    harness.first_import(wide)

    session = harness.start(SECOND)

    assert [(c.kind, c.header, c.used_by_plan) for c in session.changes] == [
        ("missing", "notas", False)
    ]
    assert session.status is SessionStatus.READY_FOR_PREVIEW


def test_a_missing_required_column_asks_for_a_role(harness):
    harness.first_import()
    without_code = [row[1:] for row in SECOND]

    session = harness.start(without_code)

    assert session.status is SessionStatus.ROLE_CONFIRMATION_REQUIRED
    assert any("product code" in issue for issue in session.role_issues)
    assert [(c.kind, c.role) for c in session.changes if c.kind == "missing"] == [
        ("missing", "code")
    ]


# -- sheet and header row --


def test_a_new_header_row_and_sheet_name_are_listed(harness):
    harness.first_import()
    harness.reader.name = "Noviembre"
    shifted = [["LISTA NOVIEMBRE", "", "", ""], *SECOND]

    session = harness.start(shifted)

    assert [(c.kind, c.old_value, c.new_value, c.old_index, c.new_index) for c in session.changes] == [
        ("sheet_changed", "Hoja1", "Noviembre", None, None),
        ("header_row_changed", None, None, 0, 1),
    ]
    assert session.status is SessionStatus.READY_FOR_PREVIEW


# -- header choice --


def test_an_ambiguous_header_waits_for_the_user_and_then_reuses_the_plan(harness):
    harness.first_import()
    headerless = SECOND[1:]

    session = harness.start(headerless)

    assert session.status is SessionStatus.HEADER_CHOICE_REQUIRED
    assert session.mode == "reuse"
    assert harness.classifier.seen_indexes == []

    session = harness.use_case.choose_header(session.id, None)

    assert session.mode == "reuse"
    assert session.based_on_plan_version == 1
    assert session.columns != ()
    assert session.status is not SessionStatus.HEADER_CHOICE_REQUIRED


# -- forcing a fresh import --


def test_a_fresh_import_can_be_forced_for_a_known_supplier(harness):
    harness.first_import()

    session = harness.start(SECOND, force_first_import=True)

    assert session.mode == "first_import"
    assert session.based_on_plan_version is None
    assert session.changes == ()
    assert set(decided_by(session).values()) == {"heuristics"}
    assert session.status is SessionStatus.QUESTIONS_PENDING


def test_the_supplier_is_matched_ignoring_case_and_spacing(harness):
    harness.first_import()
    harness.reader.rows = tuple(tuple(row) for row in SECOND)

    session = harness.use_case.start("lista.xlsx", "  FERRETERIA   ejemplo ")

    assert session.mode == "reuse"
