from decimal import Decimal

import pytest

from pricor.domain.parsing import (
    CellError,
    normalize_text,
    parse_discounts,
    parse_number,
    parse_rate,
    parse_units,
)


@pytest.mark.parametrize(
    ("text", "decimal_sep", "thousands_sep", "expected"),
    [
        ("$ 12.100,00", ",", ".", "12100.00"),
        ("U$S 850,5", ",", ".", "850.5"),
        ("ARS 1.234,56 ", ",", ".", "1234.56"),
        ("12100.00", ".", ",", "12100.00"),
        ("12,100.50", ".", ",", "12100.50"),
        ("12 100,50", ",", " ", "12100.50"),
        ("12 100,50", ",", " ", "12100.50"),
        ("12100,00", ",", ".", "12100.00"),
        ("850", ",", ".", "850"),
        ("1.234", ",", ".", "1234"),
        ("1234.5", ".", "", "1234.5"),
        ("-5,00", ",", ".", "-5.00"),
        ("15,25 USD", ",", ".", "15.25"),
    ],
)
def test_parse_number_accepts_formatted_values(text, decimal_sep, thousands_sep, expected):
    result = parse_number(text, decimal_sep, thousands_sep)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)
    assert str(result) == expected


@pytest.mark.parametrize(
    ("text", "decimal_sep", "thousands_sep"),
    [
        ("abc", ",", "."),
        ("", ",", "."),
        ("   ", ",", "."),
        ("$", ",", "."),
        ("12abc34", ",", "."),
        ("12,5,5", ",", "."),
        ("1.23", ",", "."),
        ("1.234", ",", ""),
        ("1.2.3", ".", ","),
        ("12 34", ",", "."),
        ("1e5", ",", "."),
        ("9" * 100, ",", "."),
    ],
)
def test_parse_number_rejects_unparseable_values(text, decimal_sep, thousands_sep):
    with pytest.raises(CellError):
        parse_number(text, decimal_sep, thousands_sep)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10+5", (Decimal(10), Decimal(5))),
        ("10% + 5%", (Decimal(10), Decimal(5))),
        ("7,5+5", (Decimal("7.5"), Decimal(5))),
        (" 10 ", (Decimal(10),)),
        ("", ()),
        ("   ", ()),
    ],
)
def test_parse_discounts(text, expected):
    assert parse_discounts(text) == expected


@pytest.mark.parametrize("text", ["10+abc", "10+", "+5", "150", "-5", "10++5", "abc"])
def test_parse_discounts_rejects_unreadable_values(text):
    with pytest.raises(CellError):
        parse_discounts(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("21%", "21"), ("10,5%", "10.5"), ("21", "21"), (" 10.5 % ", "10.5"), ("0", "0")],
)
def test_parse_rate(text, expected):
    assert parse_rate(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "-1", "101", "21%%"])
def test_parse_rate_rejects_invalid_values(text):
    with pytest.raises(CellError):
        parse_rate(text)


@pytest.mark.parametrize(("text", "expected"), [("10", "10"), (" 12 ", "12"), ("2,5", "2.5")])
def test_parse_units(text, expected):
    assert parse_units(text) == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [("0", "zero"), ("", "empty"), ("abc", "not a number"), ("-3", "positive")],
)
def test_parse_units_rejects_invalid_values(text, fragment):
    with pytest.raises(CellError, match=fragment):
        parse_units(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  TORNILLO AUTOP.   8x1  ", "TORNILLO AUTOP. 8x1"),
        ("00123 ", "00123"),
        ("a b", "a b"),
        ("a​b", "ab"),
        ("tab\tand\nnewline", "tab and newline"),
        ("", ""),
    ],
)
def test_normalize_text(text, expected):
    assert normalize_text(text) == expected
