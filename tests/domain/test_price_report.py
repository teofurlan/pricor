from decimal import Decimal

import pytest

from pricor.domain.contract import ContractRecord
from pricor.domain.price_report import (
    DEFAULT_ANOMALY_THRESHOLD,
    compare_price_lists,
    percent_text,
)

D = Decimal


def record(code, cost, currency="ARS", description=None):
    return ContractRecord(code, description or f"Producto {code}", D(cost), currency)


def codes(items):
    return [item.supplier_code for item in items]


def test_the_default_threshold_is_thirty_percent():
    assert DEFAULT_ANOMALY_THRESHOLD == D("0.30")


# -- increases and decreases --


def test_price_increases_and_decreases_carry_amount_and_ratio():
    previous = [record("A1", "100.00"), record("A2", "200.00")]
    current = [record("A1", "110.00"), record("A2", "150.00")]

    report = compare_price_lists(previous, current)

    (up,) = report.increases
    assert (up.supplier_code, up.previous_cost, up.current_cost) == ("A1", D("100.00"), D("110.00"))
    assert up.change == D("10.00")
    assert up.change_ratio == D("0.1")
    (down,) = report.decreases
    assert (down.supplier_code, down.change, down.change_ratio) == ("A2", D("-50.00"), D("-0.25"))
    assert report.unchanged_count == 0


def test_sections_are_sorted_with_the_biggest_moves_first():
    previous = [record(code, "100") for code in ("A1", "A2", "A3", "B1", "B2")]
    current = [
        record("A1", "105"),
        record("A2", "120"),
        record("A3", "110"),
        record("B1", "90"),
        record("B2", "70"),
    ]

    report = compare_price_lists(previous, current)

    assert codes(report.increases) == ["A2", "A3", "A1"]
    assert codes(report.decreases) == ["B2", "B1"]


def test_ties_are_broken_by_code_so_the_order_is_deterministic():
    previous = [record("B", "100"), record("A", "100")]
    current = [record("B", "110"), record("A", "110")]

    assert codes(compare_price_lists(previous, current).increases) == ["A", "B"]


def test_equal_prices_are_unchanged_whatever_their_scale():
    previous = [record("A1", "10.0"), record("A2", "5")]
    current = [record("A1", "10.00"), record("A2", "5.000")]

    report = compare_price_lists(previous, current)

    assert report.unchanged_count == 2
    assert report.increases == report.decreases == ()


def test_the_change_ratio_is_exact_decimal_arithmetic():
    report = compare_price_lists([record("A1", "0.1")], [record("A1", "0.3")])

    assert report.increases[0].change_ratio == D("2")
    assert report.increases[0].change == D("0.2")


def test_the_current_description_is_the_one_reported():
    report = compare_price_lists(
        [record("A1", "100", description="Tornillo viejo")],
        [record("A1", "110", description="Tornillo nuevo")],
    )

    assert report.increases[0].description == "Tornillo nuevo"


# -- matching --


def test_codes_match_after_normalization():
    previous = [record("  ab-1 ", "100"), record("X  Y", "100")]
    current = [record("AB-1", "110"), record("x y", "100")]

    report = compare_price_lists(previous, current)

    assert codes(report.increases) == ["AB-1"]
    assert report.unchanged_count == 1
    assert report.new_products == report.discontinued == ()


def test_leading_zeros_keep_two_codes_apart():
    report = compare_price_lists([record("00123", "10")], [record("123", "10")])

    assert codes(report.new_products) == ["123"]
    assert codes(report.discontinued) == ["00123"]


# -- new and discontinued --


def test_new_and_discontinued_products():
    previous = [record("A1", "100"), record("OLD", "50", "USD")]
    current = [record("A1", "100"), record("NEW", "75.50")]

    report = compare_price_lists(previous, current)

    (new,) = report.new_products
    assert (new.supplier_code, new.currency, new.unit_cost_net) == ("NEW", "ARS", D("75.50"))
    (gone,) = report.discontinued
    assert (gone.supplier_code, gone.currency, gone.unit_cost_net) == ("OLD", "USD", D("50"))
    assert report.unchanged_count == 1


def test_new_and_discontinued_are_sorted_by_code():
    report = compare_price_lists(
        [record("D2", "1"), record("D1", "1")], [record("N2", "1"), record("N1", "1")]
    )

    assert codes(report.new_products) == ["N1", "N2"]
    assert codes(report.discontinued) == ["D1", "D2"]


# -- currencies are never converted --


def test_a_changed_currency_is_reported_apart_without_a_percentage():
    previous = [record("A1", "100", "ARS"), record("A2", "100", "ARS")]
    current = [record("A1", "0.10", "USD"), record("A2", "100", "ARS")]

    report = compare_price_lists(previous, current)

    (moved,) = report.currency_changed
    assert (moved.supplier_code, moved.previous_currency, moved.current_currency) == (
        "A1",
        "ARS",
        "USD",
    )
    assert (moved.previous_cost, moved.current_cost) == (D("100"), D("0.10"))
    assert report.increases == report.decreases == report.anomalies == ()
    assert report.unchanged_count == 1


def test_costs_are_compared_in_the_currency_they_were_imported_in():
    report = compare_price_lists([record("A1", "10", "USD")], [record("A1", "11", "USD")])

    assert report.increases[0].currency == "USD"
    assert report.increases[0].change_ratio == D("0.1")


def test_currency_codes_compare_ignoring_case_and_spacing():
    report = compare_price_lists([record("A1", "10", "ars")], [record("A1", "10", " ARS ")])

    assert report.currency_changed == ()
    assert report.unchanged_count == 1


# -- anomalies --


@pytest.mark.parametrize(
    ("current", "anomaly"),
    [
        ("130", False),  # exactly +30%: at the threshold, not beyond it
        ("130.01", True),
        ("70", False),  # exactly -30%
        ("69.99", True),
        ("131", True),
        ("0", True),  # a price that dropped to zero is -100%
    ],
)
def test_the_threshold_is_strict(current, anomaly):
    report = compare_price_lists([record("A1", "100")], [record("A1", current)])

    changes = report.increases + report.decreases
    assert [item.anomaly for item in changes] == [anomaly]
    assert (codes(report.anomalies) == ["A1"]) is anomaly


def test_the_threshold_is_a_parameter():
    previous = [record("A1", "100"), record("A2", "100")]
    current = [record("A1", "106"), record("A2", "102")]

    default = compare_price_lists(previous, current)
    strict = compare_price_lists(previous, current, D("0.05"))

    assert default.anomalies == ()
    assert codes(strict.anomalies) == ["A1"]
    assert strict.threshold == D("0.05")


def test_a_threshold_of_zero_flags_every_change_and_none_of_the_unchanged():
    report = compare_price_lists(
        [record("A1", "100"), record("A2", "100")],
        [record("A1", "100.01"), record("A2", "100")],
        D("0"),
    )

    assert codes(report.anomalies) == ["A1"]


def test_anomalies_keep_their_place_in_increases_and_decreases():
    report = compare_price_lists(
        [record("A1", "100"), record("A2", "100")], [record("A1", "400"), record("A2", "10")]
    )

    assert codes(report.increases) == ["A1"] and report.increases[0].anomaly
    assert codes(report.decreases) == ["A2"] and report.decreases[0].anomaly
    assert codes(report.anomalies) == ["A1", "A2"]  # biggest swing first


@pytest.mark.parametrize("threshold", [D("-0.1"), D("NaN"), D("Infinity")])
def test_an_unusable_threshold_is_refused(threshold):
    with pytest.raises(ValueError, match="threshold"):
        compare_price_lists([], [], threshold)


# -- a zero previous cost --


def test_a_price_that_rises_from_zero_is_classified_explicitly_not_divided():
    report = compare_price_lists([record("A1", "0")], [record("A1", "12.50")])

    assert report.increases == report.decreases == ()
    (item,) = report.from_zero
    assert item.change == D("12.50")
    assert item.change_ratio is None
    assert item.anomaly is True
    assert codes(report.anomalies) == ["A1"]


def test_zero_to_zero_is_unchanged():
    report = compare_price_lists([record("A1", "0")], [record("A1", "0.00")])

    assert report.unchanged_count == 1
    assert report.from_zero == ()


def test_from_zero_items_lead_the_anomalies():
    report = compare_price_lists(
        [record("A1", "100"), record("A2", "0")], [record("A1", "900"), record("A2", "5")]
    )

    assert codes(report.anomalies) == ["A2", "A1"]


# -- duplicate codes --


def test_a_code_that_repeats_in_one_list_is_left_out_and_reported():
    previous = [record("A1", "100"), record("A2", "100")]
    current = [record("A1", "110"), record("A1", "999"), record("A2", "100")]

    report = compare_price_lists(previous, current)

    assert report.increases == report.new_products == report.discontinued == ()
    (ambiguous,) = report.ambiguous_codes
    assert (ambiguous.supplier_code, ambiguous.previous_count, ambiguous.current_count) == (
        "A1",
        1,
        2,
    )
    assert report.unchanged_count == 1


def test_duplicates_are_detected_after_normalization_and_in_either_list():
    previous = [record("a-1", "100"), record("A-1 ", "100"), record("B", "10")]
    current = [record("A-1", "100"), record("B", "10")]

    report = compare_price_lists(previous, current)

    assert [(a.supplier_code, a.previous_count, a.current_count) for a in report.ambiguous_codes] == [
        ("a-1", 2, 1)
    ]
    assert report.discontinued == report.new_products == ()
    assert report.unchanged_count == 1


def test_a_code_repeated_in_both_lists_is_reported_once():
    report = compare_price_lists(
        [record("A", "1"), record("A", "2")], [record("A", "1"), record("A", "3")]
    )

    assert [(a.previous_count, a.current_count) for a in report.ambiguous_codes] == [(2, 2)]


# -- summary --


def test_the_summary_counts_every_section_and_gives_the_median_change():
    previous = [record(f"U{n}", "100") for n in range(3)]
    previous += [record("D1", "100"), record("Z", "0"), record("S", "10"), record("GONE", "1")]
    previous += [record("C", "5", "ARS"), record("X", "1"), record("X", "2")]
    current = [record("U0", "102"), record("U1", "104"), record("U2", "150")]
    current += [record("D1", "90"), record("Z", "4"), record("S", "10"), record("NEW", "1")]
    current += [record("C", "5", "USD"), record("X", "1")]

    summary = compare_price_lists(previous, current).summary

    assert summary.unchanged == 1
    assert summary.increases == 3
    assert summary.decreases == 1
    assert summary.from_zero == 1
    assert summary.new_products == 1
    assert summary.discontinued == 1
    assert summary.currency_changed == 1
    assert summary.ambiguous == 1
    assert summary.anomalies == 2  # U2 at +50% and the price that left zero
    assert summary.median_change == D("0.03")  # of -10%, +2%, +4% and +50%: (2% + 4%) / 2


def test_the_median_of_an_odd_number_of_changes_is_the_middle_one():
    previous = [record(f"A{n}", "100") for n in range(3)]
    current = [record("A0", "101"), record("A1", "105"), record("A2", "103")]

    assert compare_price_lists(previous, current).summary.median_change == D("0.03")


def test_the_median_of_an_even_number_of_changes_is_the_mean_of_the_middle_two():
    previous = [record(f"A{n}", "100") for n in range(4)]
    current = [record("A0", "101"), record("A1", "103"), record("A2", "105"), record("A3", "107")]

    assert compare_price_lists(previous, current).summary.median_change == D("0.04")


def test_the_median_is_none_when_nothing_changed():
    report = compare_price_lists([record("A1", "100")], [record("A1", "100")])

    assert report.summary.median_change is None


def test_the_median_only_looks_at_products_with_a_percentage():
    previous = [record("A1", "100"), record("Z", "0"), record("C", "1", "ARS")]
    current = [record("A1", "108"), record("Z", "9"), record("C", "9", "USD")]

    assert compare_price_lists(previous, current).summary.median_change == D("0.08")


def test_empty_lists_give_an_empty_report():
    report = compare_price_lists([], [])

    assert report.summary.unchanged == 0
    assert report.anomalies == ()
    assert report.summary.median_change is None


# -- display rounding --


@pytest.mark.parametrize(
    ("ratio", "text"),
    [
        (D("0.0423"), "4.23"),
        (D("0.04235"), "4.24"),  # half rounds away from zero
        (D("-0.04235"), "-4.24"),
        (D("0.1"), "10.00"),
        (D("-0.25"), "-25.00"),
        (D("0"), "0.00"),
        (D("3"), "300.00"),
        (D("0.000049"), "0.00"),
    ],
)
def test_percent_text_rounds_half_up_to_two_places_for_display_only(ratio, text):
    assert percent_text(ratio) == text


# -- exchange rates never count as supplier price changes --


def converted(code, rate):
    return ContractRecord(
        code,
        f"Producto {code}",
        D("2.50"),
        "USD",
        unit_cost_net_converted=D("2.50") * D(rate),
        fx_rate=D(rate),
        fx_source="dolarapi:oficial:venta",
        fx_date="2026-10-14",
    )


def test_a_moving_exchange_rate_alone_is_not_a_price_change():
    report = compare_price_lists([converted("A1", "1500")], [converted("A1", "2000")])

    assert report.summary.unchanged == 1
    assert (report.increases, report.decreases, report.anomalies) == ((), (), ())
