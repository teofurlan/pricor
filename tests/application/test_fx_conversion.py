"""Currency conversion inside the import session: the rate is a per-run snapshot, never guessed."""

from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.errors import InvalidInputError, InvalidOperationError
from pricor.application.report_price_changes import ReportPriceChanges
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.domain.fx import FxSnapshot
from pricor.domain.roles import ColumnRole as R
from pricor.ports.fx_rates import FxUnavailableError
from pricor.ports.import_session import SessionStatus

from .fakes import FakeClassifier, FakeReader

ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Moneda": (R.CURRENCY, 0.95),
    "Precio": (R.COST_PRICE, 0.9),
}
HEADER = ["Codigo", "Descripcion", "Moneda", "Precio"]
WEEK1 = [
    HEADER,
    ["A1", "Antenna", "$", "1846"],
    ["A2", "Mini antenna", "u$s", "2.50"],
    ["A3", "Cable", "u$s", "10"],
]
WEEK2 = [
    HEADER,
    ["A1", "Antenna", "$", "1846"],
    ["A2", "Mini antenna", "u$s", "2.50"],
    ["A3", "Cable", "u$s", "10"],
]
CONFIRMED_MAP = 'map:{"$":"ARS","u$s":"USD"}'  # what the user confirms for the Moneda column
QUOTED = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


class FakeFx:
    """Hands out queued rates; an `Exception` in the queue is raised instead."""

    def __init__(self, *rates):
        self.rates = list(rates)
        self.calls = []

    def snapshot(self, from_currency, to_currency, rate_type, side):
        self.calls.append((from_currency, to_currency, rate_type, side))
        item = self.rates.pop(0) if len(self.rates) > 1 else self.rates[0]
        if isinstance(item, Exception):
            raise item
        rate, stale = item if isinstance(item, tuple) else (item, False)
        return FxSnapshot(
            Decimal(rate), rate_type, side, "dolarapi", QUOTED, from_currency, to_currency, stale
        )


class Harness:
    def __init__(self, fx, **kwargs):
        self.reader = FakeReader(WEEK1)
        self.database = SqliteDatabase(":memory:")
        ids = (f"s{n}" for n in count(1))
        clock = iter(datetime(2026, 10, day, tzinfo=UTC) for day in range(1, 29))
        self.fx = fx
        self.use_case = ReuseSupplierPlan(
            self.reader,
            self.database.sessions,
            [ClassifierStage("heuristics", FakeClassifier(ROLES))],
            plans=self.database.plans,
            approvals=self.database,
            id_factory=lambda: next(ids),
            clock=lambda: next(clock),
            fx=fx,
            **kwargs,
        )

    def start(self, rows=WEEK1, **kwargs):
        self.reader.rows = tuple(tuple(row) for row in rows)
        return self.use_case.start("lista.xlsx", "Emilio", **kwargs)

    def answer(self, session, **answers):
        for question_id, option in answers.items():
            self.use_case.answer(session.id, question_id, option)
        return self.use_case.get(session.id)

    def confirmed_currencies(self, rows=WEEK1):
        """The user confirmed the currency map; the conversion question is what is left."""
        return self.answer(self.start(rows), price_includes_vat="no", currency=CONFIRMED_MAP)

    def converted_session(self, rows=WEEK1, option="oficial:venta"):
        session = self.start(rows)
        return self.answer(
            session, price_includes_vat="no", currency=CONFIRMED_MAP, fx_conversion=option
        )

    def record(self, session, code):
        page = self.use_case.preview(session.id)
        return next(item.record for item in page.items if item.record["supplier_code"] == code)


@pytest.fixture
def make():
    harnesses = []

    def factory(fx, **kwargs):
        harnesses.append(Harness(fx, **kwargs))
        return harnesses[-1]

    yield factory
    for harness in harnesses:
        harness.database.close()


def test_foreign_prices_raise_the_conversion_question_and_nothing_is_applied(make):
    fx = FakeFx("1535")
    session = make(fx).confirmed_currencies()

    assert [q.id.value for q in session.questions].count("fx_conversion") == 1
    assert session.status is SessionStatus.QUESTIONS_PENDING
    assert fx.calls == []


def test_the_default_rate_type_is_only_a_suggestion_from_the_setting(make):
    session = make(FakeFx("1535"), default_fx_rate_type="blue").confirmed_currencies()

    question = next(q for q in session.questions if q.id.value == "fx_conversion")
    assert (question.suggestion.option, question.suggestion.suggested_by) == ("blue:venta", "setting")
    tokens = [option.token for option in question.options]
    assert tokens[0] == "keep" and "manual" in tokens and "oficial:compra" in tokens
    assert "fx_conversion" not in {parameter.value for parameter in session.answers}


def test_the_setting_defaults_to_the_official_rate(make):
    session = make(FakeFx("1535")).confirmed_currencies()

    question = next(q for q in session.questions if q.id.value == "fx_conversion")
    assert question.suggestion.option == "oficial:venta"


def test_confirming_a_rate_type_snapshots_a_fresh_rate_for_the_run(make):
    fx = FakeFx("1535")
    harness = make(fx)

    session = harness.converted_session()

    assert fx.calls == [("USD", "ARS", "oficial", "venta")]
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.fx_snapshot.rate == Decimal("1535")
    assert session.fx_snapshot.stale is False


def test_preview_shows_original_and_converted_costs_for_foreign_rows_only(make):
    harness = make(FakeFx("1535"))
    session = harness.converted_session()

    foreign = harness.record(session, "A2")
    pesos = harness.record(session, "A1")

    assert (foreign["unit_cost_net"], foreign["currency"]) == ("2.50", "USD")
    assert foreign["unit_cost_net_converted"] == "3837.50"
    assert foreign["fx_rate"] == "1535" and foreign["fx_source"] == "dolarapi:oficial:venta"
    assert foreign["fx_date"] == "2026-10-14"
    assert pesos["unit_cost_net_converted"] is None


def test_an_unreachable_rate_blocks_preview_and_approval_and_asks_for_a_rate(make):
    harness = make(FakeFx(FxUnavailableError("cannot reach DolarAPI")))

    session = harness.converted_session()

    assert session.status is SessionStatus.FX_RATE_REQUIRED
    assert session.fx_snapshot is None
    assert "cannot reach DolarAPI" in session.fx_error
    with pytest.raises(InvalidOperationError):
        harness.use_case.preview(session.id)
    with pytest.raises(InvalidOperationError):
        harness.use_case.approve(session.id)


def test_a_manual_rate_unblocks_the_session(make):
    harness = make(FakeFx(FxUnavailableError("down")))
    session = harness.converted_session()

    session = harness.use_case.set_manual_rate(session.id, "1.420,50")

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.fx_error is None
    assert (session.fx_snapshot.source, session.fx_snapshot.rate) == ("manual", Decimal("1420.50"))
    assert harness.record(session, "A2")["unit_cost_net_converted"] == "3551.25"
    assert harness.record(session, "A2")["fx_source"] == "manual"


def test_choosing_manual_never_calls_the_live_source(make):
    fx = FakeFx("1535")
    harness = make(fx)

    session = harness.converted_session(option="manual")

    assert fx.calls == []
    assert session.status is SessionStatus.FX_RATE_REQUIRED
    session = harness.use_case.set_manual_rate(session.id, "1500")
    assert session.status is SessionStatus.READY_FOR_PREVIEW


def test_a_stale_cached_rate_is_attached_flagged_and_still_overridable(make):
    harness = make(FakeFx(("1500", True)))

    session = harness.converted_session()

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert session.fx_snapshot.stale is True
    session = harness.use_case.set_manual_rate(session.id, "1600")
    assert session.fx_snapshot.stale is False


def test_without_any_rate_source_the_session_asks_for_a_manual_rate(make):
    harness = make(None)

    session = harness.converted_session()

    assert session.status is SessionStatus.FX_RATE_REQUIRED
    assert session.fx_error


def test_keeping_the_original_currency_needs_no_rate(make):
    fx = FakeFx("1535")
    harness = make(fx)

    session = harness.converted_session(option="keep")

    assert session.status is SessionStatus.READY_FOR_PREVIEW
    assert fx.calls == []
    assert harness.record(session, "A2")["unit_cost_net_converted"] is None


def test_changing_the_answer_refetches_the_matching_rate(make):
    fx = FakeFx("1535", "1550")
    harness = make(fx)
    session = harness.converted_session()

    session = harness.answer(session, fx_conversion="blue:compra")

    assert fx.calls[-1] == ("USD", "ARS", "blue", "compra")
    assert session.fx_snapshot.rate == Decimal("1550")


def test_a_bad_manual_rate_is_refused(make):
    harness = make(FakeFx("1535"))
    session = harness.converted_session()

    for text in ("", "abc", "0", "-3"):
        with pytest.raises(InvalidInputError):
            harness.use_case.set_manual_rate(session.id, text)
    assert harness.use_case.get(session.id).fx_snapshot.rate == Decimal("1535")


def test_a_manual_rate_makes_no_sense_without_a_conversion(make):
    harness = make(FakeFx("1535"))
    session = harness.converted_session(option="keep")

    with pytest.raises(InvalidOperationError):
        harness.use_case.set_manual_rate(session.id, "1500")


def test_refreshing_asks_the_live_source_again(make):
    fx = FakeFx("1535", "1540")
    harness = make(fx)
    session = harness.converted_session()

    session = harness.use_case.refresh_fx(session.id)

    assert session.fx_snapshot.rate == Decimal("1540")


def test_approval_stores_the_snapshot_and_the_converted_values_with_the_import(make):
    harness = make(FakeFx("1535"))
    session = harness.converted_session()

    approved = harness.use_case.approve(session.id)

    history = harness.database.history
    assert history.fx_of(approved.id) == approved.fx_snapshot
    by_code = {item.record.supplier_code: item.record for item in history.records_of(approved.id)}
    assert by_code["A2"].unit_cost_net == Decimal("2.50")  # the supplier's value is kept
    assert by_code["A2"].unit_cost_net_converted == Decimal("3837.50")
    assert by_code["A1"].unit_cost_net_converted is None


def test_reuse_keeps_the_rate_type_but_snapshots_a_fresh_rate_and_asks_nothing(make):
    fx = FakeFx("1535", "1600")
    harness = make(fx)
    harness.use_case.approve(harness.converted_session().id)

    second = harness.start(WEEK2)

    assert second.mode == "reuse"
    assert second.questions == ()
    assert second.status is SessionStatus.READY_FOR_PREVIEW
    assert fx.calls[-1] == ("USD", "ARS", "oficial", "venta")
    assert second.fx_snapshot.rate == Decimal("1600")
    assert harness.record(second, "A2")["unit_cost_net_converted"] == "4000.00"
    stored = harness.database.plans.latest_for("Emilio").plan
    assert "1535" not in repr(stored) and "1600" not in repr(stored)  # the plan never holds a rate


def test_reuse_with_the_source_down_asks_for_a_rate_instead_of_reusing_the_old_one(make):
    fx = FakeFx("1535", FxUnavailableError("down"))
    harness = make(fx)
    harness.use_case.approve(harness.converted_session().id)

    second = harness.start(WEEK2)

    assert second.status is SessionStatus.FX_RATE_REQUIRED
    assert second.fx_snapshot is None


def test_the_price_report_ignores_exchange_rate_movements(make):
    harness = make(FakeFx("1535", "1900"))  # the dollar jumps 24% between the two runs
    first = harness.use_case.approve(harness.converted_session().id)
    second = harness.use_case.approve(harness.start(WEEK2).id)

    report = ReportPriceChanges(harness.use_case.get, harness.database.history).compare(second.id)

    assert harness.database.history.fx_of(first.id).rate != harness.database.history.fx_of(second.id).rate
    summary = report.report.summary
    assert (summary.increases, summary.decreases, summary.anomalies) == (0, 0, 0)
    assert summary.unchanged == 3
    assert report.report.anomalies == ()
