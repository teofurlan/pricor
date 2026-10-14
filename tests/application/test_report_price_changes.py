from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pricor.application.errors import (
    InvalidInputError,
    InvalidOperationError,
    NoPreviousImportError,
)
from pricor.application.report_price_changes import ReportPriceChanges, parse_threshold
from pricor.domain.price_report import DEFAULT_ANOMALY_THRESHOLD

from .test_reuse_supplier_plan import FIRST, SECOND, Harness


class FakeReportExporter:
    media_type = "text/plain"
    extension = ".txt"

    def __init__(self):
        self.reports = []

    def export(self, report):
        self.reports.append(report)
        return b"report"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self):
        self.now += timedelta(days=7)
        return self.now


@pytest.fixture
def harness():
    harness = Harness(clock=Clock())  # imports must have distinct, increasing dates
    yield harness
    harness.database.close()


def reporter(harness, exporter=None):
    return ReportPriceChanges(harness.use_case.get, harness.database.history, exporter)


def approve(harness, rows):
    session = harness.start(rows)
    if session.questions:
        session = harness.answer(session, price_includes_vat="yes", currency="ARS")
    return harness.use_case.approve(session.id)


def test_a_session_that_is_not_approved_has_no_report(harness):
    approve(harness, FIRST)
    pending = harness.start(SECOND)

    with pytest.raises(InvalidOperationError, match="approve"):
        reporter(harness).compare(pending.id)


def test_the_first_import_of_a_supplier_has_nothing_to_compare_with(harness):
    first = approve(harness, FIRST)

    with pytest.raises(NoPreviousImportError):
        reporter(harness).compare(first.id)


def test_an_import_is_compared_with_the_previous_approved_import(harness):
    first = approve(harness, FIRST)
    second = approve(harness, SECOND)

    comparison = reporter(harness).compare(second.id)

    assert comparison.previous.import_id == first.id
    assert comparison.current.import_id == second.id
    assert comparison.current.supplier_name == "Ferreteria Ejemplo"
    report = comparison.report
    assert [(item.supplier_code, item.change_ratio) for item in report.increases] == [
        ("A1", Decimal("0.1")),
        ("A3", Decimal("0.1")),
    ]
    assert [item.supplier_code for item in report.new_products] == ["A5"]
    assert report.unchanged_count == 2
    assert report.threshold == DEFAULT_ANOMALY_THRESHOLD


def test_the_comparison_uses_the_net_cost_not_the_raw_cell(harness):
    approve(harness, FIRST)
    second = approve(harness, SECOND)

    (item, _) = reporter(harness).compare(second.id).report.increases

    assert (item.previous_cost, item.current_cost) == (Decimal("1000.00"), Decimal("1100.00"))
    assert item.currency == "ARS"


def test_with_three_imports_each_one_is_compared_with_the_one_before(harness):
    first = approve(harness, FIRST)
    second = approve(harness, SECOND)
    third = approve(harness, SECOND)

    older = reporter(harness).compare(second.id)
    newer = reporter(harness).compare(third.id)

    assert older.previous.import_id == first.id
    assert newer.previous.import_id == second.id
    assert newer.report.increases == ()
    assert newer.report.unchanged_count == 5


def test_other_suppliers_imports_are_never_compared(harness):
    first = approve(harness, FIRST)
    other = harness.use_case.start("otra.xlsx", "Otra Ferreteria")
    harness.answer(other, price_includes_vat="yes", currency="ARS")
    harness.use_case.approve(other.id)
    second = approve(harness, SECOND)

    comparison = reporter(harness).compare(second.id)

    assert comparison.previous.import_id == first.id


def test_the_anomaly_threshold_is_a_parameter(harness):
    approve(harness, FIRST)
    second = approve(harness, SECOND)

    default = reporter(harness).compare(second.id)
    strict = reporter(harness).compare(second.id, Decimal("0.05"))

    assert default.report.anomalies == ()
    assert [item.supplier_code for item in strict.report.anomalies] == ["A1", "A3"]


def test_an_approved_session_missing_from_the_history_is_reported_not_guessed(harness):
    approve(harness, FIRST)
    second = approve(harness, SECOND)
    stranger = ReportPriceChanges(harness.use_case.get, _EmptyHistory(), None)

    with pytest.raises(InvalidOperationError, match="history"):
        stranger.compare(second.id)


class _EmptyHistory:
    def imports_for(self, supplier):
        return ()


def test_the_report_is_exported_through_the_exporter_with_a_descriptive_name(harness):
    approve(harness, FIRST)
    second = approve(harness, SECOND)
    exporter = FakeReportExporter()

    file = reporter(harness, exporter).export(second.id)

    assert file.content == b"report"
    assert file.media_type == "text/plain"
    assert file.filename == f"pricor-ferreteria-ejemplo-{second.id[:8]}-price-changes.txt"
    assert exporter.reports[0].unchanged_count == 2


def test_exporting_without_an_exporter_is_refused(harness):
    approve(harness, FIRST)
    second = approve(harness, SECOND)

    with pytest.raises(InvalidOperationError):
        reporter(harness).export(second.id)


@pytest.mark.parametrize(("text", "value"), [("0.30", "0.30"), ("0", "0"), ("1.5", "1.5"), (" 0.2 ", "0.2")])
def test_a_threshold_is_a_ratio_written_as_a_decimal(text, value):
    assert parse_threshold(text) == Decimal(value)


@pytest.mark.parametrize("text", ["", "abc", "-0.1", "nan", "inf", "30%", "0,3"])
def test_an_unreadable_threshold_is_refused(text):
    with pytest.raises(InvalidInputError, match="threshold"):
        parse_threshold(text)


def test_no_threshold_means_the_default():
    assert parse_threshold(None) == DEFAULT_ANOMALY_THRESHOLD
