from pricor.domain.plan_builder import (
    ColumnSource,
    ConstantSource,
    FxChoice,
    KeepOriginalCurrency,
    PlanParameters,
    RoleAssignment,
    build_plan,
)
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole as R

HEADERS = ["Code", "Name", "Price", "Currency"]
ROLES = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.CURRENCY]


def build(currency, fx=None, rows=None, roles=ROLES):
    rows = rows or [["A1", "Antenna", "1846", "$"], ["A2", "Antenna mini", "2.588", "u$s"]]
    profile = profile_sheet([HEADERS, *rows])
    assignments = [RoleAssignment(c, r) for c, r in zip(profile.columns, roles, strict=True)]
    parameters = PlanParameters(
        supplier="Emilio",
        price_includes_vat=False,
        price_is_per_pack=False,
        decimal_sep=".",
        thousands_sep="",
        currency=currency,
        fx=fx,
    )
    return build_plan(assignments, parameters)


def unresolved_ids(result):
    return [item.parameter for item in result.unresolved]


def steps(result):
    return [step.op.value for step in result.plan.steps]


def test_foreign_prices_raise_the_conversion_question_and_never_default():
    result = build(ConstantSource("USD"))

    assert result.plan is None
    assert unresolved_ids(result) == ["fx_conversion"]


def test_a_chosen_rate_adds_the_conversion_as_the_last_step():
    result = build(ConstantSource("USD"), FxChoice("oficial", "venta"))

    assert steps(result)[-1] == "convert_currency"
    step = result.plan.steps[-1]
    assert (step.from_currency, step.to_currency, step.rate_type, step.side) == (
        "USD",
        "ARS",
        "oficial",
        "venta",
    )


def test_keeping_the_original_currency_adds_no_step_and_no_question():
    result = build(ConstantSource("USD"), KeepOriginalCurrency())

    assert result.unresolved == ()
    assert "convert_currency" not in steps(result)


def test_prices_already_in_pesos_never_ask_about_conversion():
    result = build(ConstantSource("ARS"))

    assert result.unresolved == ()
    assert "convert_currency" not in steps(result)


def test_an_answer_that_no_longer_applies_leaves_the_plan_without_conversion():
    result = build(ConstantSource("ARS"), FxChoice("blue", "compra"))

    assert result.unresolved == ()
    assert "convert_currency" not in steps(result)


MIXED = ColumnSource({"$": "ARS", "u$s": "USD"})


def test_a_confirmed_mixed_currency_column_asks_about_the_dollars():
    result = build(MIXED)

    assert unresolved_ids(result) == ["fx_conversion"]


def test_a_mixed_currency_column_converts_only_the_foreign_values():
    result = build(MIXED, FxChoice("oficial", "venta"))

    mapping = next(s for s in result.plan.steps if s.op.value == "map_values" and s.to.value == "currency")
    assert dict(mapping.table) == {"$": "ARS", "u$s": "USD"}
    assert result.plan.steps[-1].from_currency == "USD"


def test_currency_values_that_are_not_recognized_still_need_the_user():
    rows = [["A1", "X", "10", "pesos"], ["A2", "Y", "20", "moneda rara"]]

    result = build(None, rows=rows)

    assert unresolved_ids(result) == ["currency"]


def test_more_than_one_foreign_currency_cannot_be_converted_with_one_rate():
    rows = [["A1", "X", "10", "u$s"], ["A2", "Y", "20", "eur"]]

    result = build(ColumnSource({"u$s": "USD", "eur": "EUR"}), FxChoice("oficial", "venta"), rows=rows)

    assert unresolved_ids(result) == ["fx_currencies"]


def test_an_explicit_column_source_wins_over_the_inferred_values():
    result = build(ColumnSource({"$": "ARS", "u$s": "EUR"}), FxChoice("oficial", "venta"))

    assert result.plan.steps[-1].from_currency == "EUR"
