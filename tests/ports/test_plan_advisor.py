from decimal import Decimal

import pytest

from pricor.domain.plan_builder import ColumnSource, ConstantSource, PlanParameters
from pricor.ports.plan_advisor import (
    ParameterId,
    SeparatorChoice,
    parse_value,
    with_answer,
)

P = ParameterId


@pytest.mark.parametrize(
    ("parameter", "token", "expected"),
    [
        (P.PRICE_INCLUDES_VAT, "yes", True),
        (P.PRICE_INCLUDES_VAT, "no", False),
        (P.PRICE_IS_PER_PACK, "yes", True),
        (P.VAT_RATE, "column", ColumnSource()),
        (P.VAT_RATE, "constant:21", ConstantSource(Decimal(21))),
        (P.VAT_RATE, "constant:10.5", ConstantSource(Decimal("10.5"))),
        (P.UNITS_PER_PACK, "column", ColumnSource()),
        (P.UNITS_PER_PACK, "constant:12", ConstantSource(Decimal(12))),
        (P.DISCOUNTS, "column", ColumnSource()),
        (P.DISCOUNTS, "none", ConstantSource(())),
        (P.DISCOUNTS, "constant:10+5", ConstantSource((Decimal(10), Decimal(5)))),
        (P.CURRENCY, "ARS", ConstantSource("ARS")),
        (P.CURRENCY, "USD", ConstantSource("USD")),
        (P.NUMBER_FORMAT, "decimal_comma", SeparatorChoice(",", ".")),
        (P.NUMBER_FORMAT, "decimal_point", SeparatorChoice(".", ",")),
    ],
)
def test_parse_value_accepts_the_closed_vocabulary(parameter, token, expected):
    assert parse_value(parameter, token) == expected


@pytest.mark.parametrize(
    ("parameter", "token"),
    [
        (P.PRICE_INCLUDES_VAT, "maybe"),
        (P.PRICE_INCLUDES_VAT, "True"),
        (P.VAT_RATE, "constant:abc"),
        (P.VAT_RATE, "constant:101"),
        (P.VAT_RATE, "constant:-1"),
        (P.VAT_RATE, "constant:__import__('os')"),
        (P.UNITS_PER_PACK, "constant:0"),
        (P.UNITS_PER_PACK, "constant:1e3"),
        (P.DISCOUNTS, "constant:10+x"),
        (P.DISCOUNTS, "constant:150"),
        (P.CURRENCY, "BTC"),
        (P.CURRENCY, "ars"),
        (P.NUMBER_FORMAT, "decimal_semicolon"),
        (P.PRICE_IS_PER_PACK, ""),
    ],
)
def test_parse_value_rejects_everything_else(parameter, token):
    with pytest.raises(ValueError):
        parse_value(parameter, token)


def test_with_answer_fills_the_matching_parameter_field():
    base = PlanParameters(supplier="Acme")

    assert with_answer(base, P.PRICE_INCLUDES_VAT, True).price_includes_vat is True
    assert with_answer(base, P.PRICE_IS_PER_PACK, False).price_is_per_pack is False
    assert with_answer(base, P.VAT_RATE, ColumnSource()).vat_source == ColumnSource()
    assert with_answer(base, P.UNITS_PER_PACK, ConstantSource(Decimal(6))).units_source == (
        ConstantSource(Decimal(6))
    )
    assert with_answer(base, P.DISCOUNTS, ColumnSource()).discounts == ColumnSource()
    assert with_answer(base, P.CURRENCY, ConstantSource("USD")).currency == ConstantSource("USD")
    separators = with_answer(base, P.NUMBER_FORMAT, SeparatorChoice(",", "."))
    assert (separators.decimal_sep, separators.thousands_sep) == (",", ".")
    assert base == PlanParameters(supplier="Acme")


def test_with_answer_rejects_a_value_of_the_wrong_kind():
    with pytest.raises(ValueError):
        with_answer(PlanParameters(supplier="Acme"), P.PRICE_INCLUDES_VAT, ColumnSource())
