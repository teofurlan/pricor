from decimal import Decimal

import pytest

from pricor.domain.contract import ContractRecord
from pricor.domain.engine import PlanIncompatibleError, execute_plan
from pricor.domain.plan import parse_plan

from .golden import GOLDEN_HEADERS, golden_plan_dict

GOLDEN_ROW = ["00123 ", "  TORNILLO AUTOP.   8x1  ", "$ 12.100,00", "10", "10+5", "21%"]


def run(rows, plan_dict=None, headers=None):
    plan = parse_plan(plan_dict or golden_plan_dict())
    return execute_plan(plan, headers or GOLDEN_HEADERS, rows)


def row_with(**overrides):
    """GOLDEN_ROW with cells replaced by position name."""
    positions = {"code": 0, "desc": 1, "price": 2, "units": 3, "disc": 4, "vat": 5}
    row = list(GOLDEN_ROW)
    for name, value in overrides.items():
        row[positions[name]] = value
    return row


def test_golden_row_produces_expected_record():
    result = run([GOLDEN_ROW])

    assert len(result.accepted) == 1
    assert result.rejected == ()
    accepted = result.accepted[0]
    assert accepted.record == ContractRecord(
        supplier_code="00123",
        description="TORNILLO AUTOP. 8x1",
        unit_cost_net=Decimal("855.00"),
        currency="ARS",
        vat_rate=Decimal("21"),
        units_per_pack=Decimal("10"),
    )
    assert accepted.record.unit_cost_net.as_tuple().exponent == -2


def test_golden_row_trace_shows_every_cost_step():
    accepted = run([GOLDEN_ROW]).accepted[0]

    assert [(t.step, t.value) for t in accepted.trace] == [
        ("original", "$ 12.100,00"),
        ("parse_number", Decimal("12100.00")),
        ("apply_discounts", Decimal("10345.50")),
        ("strip_vat", Decimal("8550.00")),
        ("per_unit", Decimal("855.00")),
        ("rounding", Decimal("855.00")),
    ]


def test_non_terminating_division_keeps_precision_until_final_rounding():
    plan = golden_plan_dict()
    plan["steps"][4]["table"] = {"10,5%": 10.5}
    plan["steps"][3] = {"op": "apply_discounts", "from": {"constant": [0]}}
    row = row_with(price="1.000,00", vat="10,5%", units="3")

    accepted = run([row], plan).accepted[0]
    by_step = {t.step: t.value for t in accepted.trace}

    # 1000 / 1.105 = 904.977375565610859...; kept unrounded in the trace.
    assert by_step["strip_vat"] > Decimal("904.97737556561085")
    assert by_step["strip_vat"] < Decimal("904.97737556561086")
    # (1000 / 1.105) / 3 = 301.6591251885369...; rounded once, at the end.
    assert accepted.record.unit_cost_net == Decimal("301.66")


def test_rounding_is_half_up_not_bankers():
    plan = golden_plan_dict()
    plan["rounding"] = {"decimals": 2, "mode": "half_up"}
    plan["steps"][3] = {"op": "apply_discounts", "from": {"constant": [0]}}
    plan["steps"][4]["table"] = {"21%": 0}
    plan["steps"][5] = {"op": "strip_vat", "rate_from": {"constant": 0}}
    plan["steps"][6] = {"op": "per_unit", "units_from": {"constant": 1}}

    cents = {"1,005": "1.01", "1,015": "1.02", "1,025": "1.03", "2,675": "2.68"}
    for raw, expected in cents.items():
        record = run([row_with(price=raw)], plan).accepted[0].record
        assert record.unit_cost_net == Decimal(expected), raw


def test_money_math_never_uses_float():
    accepted = run([GOLDEN_ROW]).accepted[0]
    assert all(not isinstance(t.value, float) for t in accepted.trace)
    assert isinstance(accepted.record.unit_cost_net, Decimal)


def test_leading_zero_codes_stay_text():
    record = run([row_with(code=" 000123 ")]).accepted[0].record
    assert record.supplier_code == "000123"


def test_empty_discount_means_no_discount():
    accepted = run([row_with(disc="")]).accepted[0]
    by_step = {t.step: t.value for t in accepted.trace}
    assert by_step["apply_discounts"] == Decimal("12100.00")


def test_discount_with_percent_signs_is_tolerated():
    accepted = run([row_with(disc="10% + 5%")]).accepted[0]
    assert accepted.record.unit_cost_net == Decimal("855.00")


# --- rejection reasons -----------------------------------------------------


def only_rejection(rows, **kwargs):
    result = run(rows, **kwargs)
    assert result.accepted == ()
    assert len(result.rejected) == 1
    return result.rejected[0]


def test_zero_units_rejects_row_with_reason():
    rejected = only_rejection([row_with(units="0")])
    assert any("zero" in r for r in rejected.reasons)
    assert rejected.cells == tuple(row_with(units="0"))
    assert rejected.row_number == 1


def test_empty_units_rejects_row():
    rejected = only_rejection([row_with(units="")])
    assert any("empty" in r for r in rejected.reasons)


def test_non_numeric_units_rejects_row():
    rejected = only_rejection([row_with(units="caja")])
    assert any("not a number" in r for r in rejected.reasons)


def test_constant_units_do_not_need_the_column():
    plan = golden_plan_dict()
    plan["steps"][6] = {"op": "per_unit", "units_from": {"constant": 10}}
    record = run([row_with(units="")], plan).accepted[0].record
    assert record.unit_cost_net == Decimal("855.00")


def test_bad_price_rejects_row_with_reason():
    rejected = only_rejection([row_with(price="abc")])
    assert any("not a number" in r and "Precio x caja c/IVA" in r for r in rejected.reasons)


def test_bad_discount_rejects_row_with_reason():
    rejected = only_rejection([row_with(disc="10+abc")])
    assert any("unreadable discount" in r for r in rejected.reasons)


def test_unmapped_value_rejects_row_with_reason():
    rejected = only_rejection([row_with(vat="27%")])
    assert any("unmapped value" in r and "27%" in r for r in rejected.reasons)


def test_map_values_matches_after_normalizing_whitespace_and_case():
    plan = golden_plan_dict()
    plan["steps"][4]["table"] = {"Exento": 0}
    plan["steps"][5] = {"op": "strip_vat", "rate_from": {"constant": 21}}
    record = run([row_with(vat="  exento ")], plan).accepted[0].record
    assert record.vat_rate == Decimal("0")


def test_missing_required_text_field_rejects_row():
    rejected = only_rejection([row_with(code="   ")])
    assert any("supplier_code" in r for r in rejected.reasons)


def test_rejection_collects_reasons_from_independent_steps():
    rejected = only_rejection([row_with(code="", units="0", vat="27%")])
    joined = " | ".join(rejected.reasons)
    assert "supplier_code" in joined
    assert "zero" in joined
    assert "unmapped value" in joined


def test_cost_failure_does_not_add_noise_from_dependent_steps():
    rejected = only_rejection([row_with(price="abc")])
    assert len(rejected.reasons) == 1


def test_short_row_missing_cells_is_rejected_not_crashing():
    rejected = only_rejection([["00123", "SCREW"]])
    assert rejected.cells == ("00123", "SCREW")
    assert rejected.reasons


def test_non_string_cells_are_accepted():
    row = ["00123", "SCREW", Decimal("12100.00"), 10, None, "21%"]
    accepted = run([row]).accepted[0]
    # No discount (None cell): 12100.00 / 1.21 / 10
    assert accepted.record.unit_cost_net == Decimal("1000.00")


def test_accepted_plus_rejected_equals_input_rows():
    rows = [
        GOLDEN_ROW,
        row_with(units="0"),
        row_with(price="abc"),
        row_with(vat="99%"),
        row_with(code="", desc=""),
        [],
        row_with(),
    ]
    result = run(rows)

    assert len(result.accepted) + len(result.rejected) == len(rows)
    numbers = sorted(r.row_number for r in result.accepted) + sorted(
        r.row_number for r in result.rejected
    )
    assert sorted(numbers) == list(range(1, len(rows) + 1))


def test_first_row_number_offsets_reported_numbers():
    plan = parse_plan(golden_plan_dict())
    result = execute_plan(plan, GOLDEN_HEADERS, [GOLDEN_ROW, row_with(units="0")], first_row_number=2)
    assert result.accepted[0].row_number == 2
    assert result.rejected[0].row_number == 3


def test_negative_cost_is_rejected():
    rejected = only_rejection([row_with(price="-100,00")])
    assert any("negative" in r for r in rejected.reasons)


# --- plan / file compatibility --------------------------------------------


def test_header_mismatch_raises_listing_all_mismatches():
    headers = list(GOLDEN_HEADERS)
    headers[2] = "Precio unitario"
    headers[4] = "Descuento"

    with pytest.raises(PlanIncompatibleError) as excinfo:
        run([GOLDEN_ROW], headers=headers)

    problems = excinfo.value.problems
    assert len(problems) == 2
    assert any("column 2" in p and "Precio unitario" in p for p in problems)
    assert any("column 4" in p and "Descuento" in p for p in problems)


def test_missing_column_index_raises():
    with pytest.raises(PlanIncompatibleError) as excinfo:
        run([GOLDEN_ROW], headers=GOLDEN_HEADERS[:4])

    assert any("column 5" in p and "does not exist" in p for p in excinfo.value.problems)


def test_header_comparison_ignores_case_and_whitespace():
    headers = ["  código", "DESCRIPCIÓN ", "precio   x caja c/iva", "Unid  x caja", "BONIF.", "iva"]
    assert len(run([GOLDEN_ROW], headers=headers).accepted) == 1


def test_incompatible_plan_executes_nothing():
    headers = [h.upper() if i != 0 else "Otro" for i, h in enumerate(GOLDEN_HEADERS)]
    with pytest.raises(PlanIncompatibleError):
        run([GOLDEN_ROW], headers=headers)


def test_blank_file_header_matches_the_synthesized_plan_header():
    plan = golden_plan_dict()
    plan["steps"][2]["column"]["header"] = "column_2"
    headers = list(GOLDEN_HEADERS)
    headers[2] = ""

    result = run([GOLDEN_ROW], plan, headers)

    assert result.rejected == ()
