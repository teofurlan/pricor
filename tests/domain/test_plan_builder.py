from decimal import Decimal

import pytest

from pricor.domain.engine import execute_numbered_rows
from pricor.domain.plan import PlanValidationError, parse_plan
from pricor.domain.plan_builder import (
    ColumnSource,
    ConstantSource,
    PlanParameters,
    RoleAssignment,
    build_plan,
)
from pricor.domain.profile import engine_input, profile_sheet
from pricor.domain.roles import ColumnRole as R

from .golden import GOLDEN_HEADERS, golden_plan_dict

GOLDEN_ROW = ["00123 ", "  TORNILLO AUTOP.   8x1  ", "$ 12.100,00", "10", "10+5", "21%"]
GOLDEN_ROWS = [
    GOLDEN_ROW,
    ["00124", "ARANDELA PLANA", "$ 1.500,50", "50", "", "10,5%"],
    ["00125", "TUERCA M8", "$ 980,00", "1", "5", "21%"],
]
GOLDEN_ROLES = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.UNITS_PER_PACK, R.DISCOUNT, R.VAT_RATE]
GOLDEN_CONFIRMATIONS = ("C incluye IVA", "C es precio por caja", "moneda ARS")


def assignments_for(rows, roles, headers=GOLDEN_HEADERS):
    profile = profile_sheet([headers, *rows])
    return profile, [RoleAssignment(c, r) for c, r in zip(profile.columns, roles, strict=True)]


def golden_parameters(**overrides):
    values = {
        "supplier": "Ferretería Ejemplo",
        "price_includes_vat": True,
        "vat_source": ColumnSource(value_map={"21%": Decimal(21), "10,5%": Decimal("10.5")}),
        "price_is_per_pack": True,
        "currency": ConstantSource("ARS"),
        "confirmations": GOLDEN_CONFIRMATIONS,
    }
    values.update(overrides)
    return PlanParameters(**values)


def build(roles=GOLDEN_ROLES, rows=GOLDEN_ROWS, headers=GOLDEN_HEADERS, **overrides):
    profile, assignments = assignments_for(rows, roles, headers)
    return profile, build_plan(assignments, golden_parameters(**overrides))


def unresolved_ids(result):
    return [item.parameter for item in result.unresolved]


def op_names(result):
    return [step.op.value for step in result.plan.steps]


def test_golden_case_builds_the_note_plan_exactly():
    _, result = build()

    assert result.unresolved == ()
    assert result.plan == parse_plan(golden_plan_dict())


def test_golden_plan_executes_to_855():
    profile, result = build()
    headers, numbered = engine_input([GOLDEN_HEADERS, *GOLDEN_ROWS], profile)

    run = execute_numbered_rows(result.plan, headers, numbered)

    assert run.rejected == ()
    assert run.accepted[0].record.unit_cost_net == Decimal("855.00")


def test_separators_come_from_the_profiler_unless_overridden():
    rows = [["A1", "X", "1.500,50", "10", "", "21"]]
    _, detected = build(rows=rows, vat_source=None)
    _, overridden = build(rows=rows, vat_source=None, decimal_sep=".", thousands_sep=",")

    assert detected.plan.steps[2].decimal_sep == ","
    assert detected.plan.steps[2].thousands_sep == "."
    assert overridden.plan.steps[2].decimal_sep == "."
    assert overridden.plan.steps[2].thousands_sep == ","


def test_ambiguous_separators_are_unresolved_not_guessed():
    rows = [["A1", "X", "1.234", "10", "", "21"], ["A2", "Y", "2.500", "5", "", "21"]]

    _, result = build(rows=rows)

    assert result.plan is None
    assert "number_format" in unresolved_ids(result)


def test_unknown_vat_treatment_is_unresolved():
    _, result = build(price_includes_vat=None)

    assert result.plan is None
    assert unresolved_ids(result) == ["price_includes_vat"]


def test_prices_without_vat_skip_the_strip_vat_step():
    _, result = build(price_includes_vat=False, vat_source=None)

    assert result.unresolved == ()
    assert "strip_vat" not in op_names(result)


def test_vat_included_without_any_rate_source_is_unresolved():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.UNITS_PER_PACK, R.DISCOUNT, R.IGNORE]

    _, result = build(roles=roles, vat_source=None)

    assert unresolved_ids(result) == ["vat_rate"]


def test_constant_vat_rate_replaces_the_column():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.UNITS_PER_PACK, R.DISCOUNT, R.IGNORE]

    _, result = build(roles=roles, vat_source=ConstantSource(Decimal(21)))

    strip = next(s for s in result.plan.steps if s.op.value == "strip_vat")
    assert strip.rate_from.value == Decimal(21)


def test_vat_column_without_value_map_is_read_directly():
    _, result = build(vat_source=ColumnSource())

    strip = next(s for s in result.plan.steps if s.op.value == "strip_vat")
    assert strip.rate_from.column.header == "IVA"
    assert "map_values" not in op_names(result)


def test_unknown_currency_is_unresolved():
    _, result = build(currency=None)

    assert unresolved_ids(result) == ["currency"]


def test_currency_column_needs_a_value_map():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.UNITS_PER_PACK, R.DISCOUNT, R.CURRENCY]
    rows = [["A1", "X", "100,50", "10", "", "pesos"]]
    common = {"roles": roles, "rows": rows, "price_includes_vat": False, "vat_source": None}

    _, unmapped = build(currency=ColumnSource(), **common)
    _, mapped = build(currency=ColumnSource({"pesos": "ARS"}), **common)

    assert unresolved_ids(unmapped) == ["currency"]
    step = next(s for s in mapped.plan.steps if s.op.value == "map_values")
    assert step.to.value == "currency"
    assert dict(step.table) == {"pesos": "ARS"}


def test_per_pack_without_units_source_is_unresolved():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.IGNORE, R.DISCOUNT, R.VAT_RATE]

    _, result = build(roles=roles)

    assert unresolved_ids(result) == ["units_per_pack"]


def test_units_column_with_unknown_pack_meaning_is_unresolved():
    _, result = build(price_is_per_pack=None)

    assert unresolved_ids(result) == ["price_is_per_pack"]


def test_unit_prices_skip_the_per_unit_step():
    _, result = build(price_is_per_pack=False)

    assert result.unresolved == ()
    assert "per_unit" not in op_names(result)


def test_constant_units_per_pack():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.IGNORE, R.DISCOUNT, R.VAT_RATE]

    _, result = build(roles=roles, units_source=ConstantSource(Decimal(12)))

    step = next(s for s in result.plan.steps if s.op.value == "per_unit")
    assert step.units_from.value == Decimal(12)


def test_constant_discounts_replace_the_column():
    _, result = build(discounts=ConstantSource((Decimal(10), Decimal(5))))

    step = next(s for s in result.plan.steps if s.op.value == "apply_discounts")
    assert step.source.percents == (Decimal(10), Decimal(5))


def test_no_discount_source_omits_the_step():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.UNITS_PER_PACK, R.IGNORE, R.VAT_RATE]

    _, result = build(roles=roles)

    assert "apply_discounts" not in op_names(result)


def test_missing_required_columns_are_all_reported_together():
    roles = [R.IGNORE] * 6

    _, result = build(roles=roles)

    assert unresolved_ids(result)[:3] == ["code_column", "description_column", "cost_price_column"]


def test_two_cost_columns_are_ambiguous():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.COST_PRICE, R.DISCOUNT, R.VAT_RATE]

    _, result = build(roles=roles)

    assert "cost_price_column" in unresolved_ids(result)


def test_every_unresolved_parameter_carries_a_reason():
    _, result = build(price_includes_vat=None, currency=None)

    assert result.unresolved
    assert all(item.reason for item in result.unresolved)


def test_headerless_columns_use_synthesized_headers_that_the_engine_accepts():
    headers = ["Código", "Descripción", "", "IVA"]
    rows = [["A1", "TORNILLO", "100,50", "21%"], ["A2", "ARANDELA", "20,00", "21%"]]
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.VAT_RATE]
    profile, assignments = assignments_for(rows, roles, headers)
    params = golden_parameters(
        price_is_per_pack=False, vat_source=ColumnSource(), confirmations=()
    )

    result = build_plan(assignments, params)

    cost = next(s for s in result.plan.steps if s.op.value == "parse_number")
    assert cost.column.header == "column_2"
    engine_headers, numbered = engine_input([headers, *rows], profile)
    run = execute_numbered_rows(result.plan, engine_headers, numbered)
    assert run.rejected == ()
    assert run.accepted[0].record.unit_cost_net == Decimal("83.06")


def test_barcode_column_is_normalized_into_the_barcode_field():
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.UNITS_PER_PACK, R.BARCODE, R.VAT_RATE]

    _, result = build(roles=roles)

    targets = [
        s.to.value for s in result.plan.steps if s.op.value == "normalize_text"
    ]
    assert targets == ["supplier_code", "description", "barcode"]


def test_built_plan_always_passes_through_parse_plan():
    # A parameter combination the catalog rejects surfaces as a validation
    # error rather than being silently repaired.
    with pytest.raises(PlanValidationError):
        build(decimal_sep=",", thousands_sep=",")


def test_explicit_empty_discounts_omit_the_step_even_with_a_discount_column():
    _, result = build(discounts=ConstantSource(()))

    assert result.unresolved == ()
    assert "apply_discounts" not in op_names(result)


def test_cost_column_typed_text_leaves_number_format_unresolved():
    rows = [
        ["A1", "X", "12.100,00", "10", "", "21"],
        ["A2", "Y", "1.500,50", "5", "", "21"],
        ["A3", "Z", "980,00", "1", "", "21"],
        ["A4", "W", "consultar", "1", "", "21"],
    ]

    profile, result = build(rows=rows)

    assert profile.columns[2].apparent_type.value == "text"
    assert result.plan is None
    assert "number_format" in unresolved_ids(result)


def test_numeric_cost_column_without_any_separator_still_builds():
    rows = [["A1", "X", "100", "10", "", "21"], ["A2", "Y", "250", "5", "", "21"]]

    _, result = build(rows=rows)

    assert result.plan is not None
