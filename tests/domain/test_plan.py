import json
from decimal import Decimal

import pytest

from pricor.domain.contract import TargetField
from pricor.domain.plan import (
    ApplyDiscounts,
    ColumnDiscounts,
    ColumnRef,
    Constant,
    ConstantDiscounts,
    FromColumn,
    FromConstant,
    FromField,
    MapValues,
    NormalizeText,
    Operation,
    ParseNumber,
    PerUnit,
    PlanValidationError,
    StripVat,
    parse_plan,
    plan_to_dict,
)

from .golden import golden_plan_dict


def problems_for(data) -> list[str]:
    with pytest.raises(PlanValidationError) as excinfo:
        parse_plan(data)
    return excinfo.value.problems


def step_index(data: dict, op: str) -> int:
    return next(i for i, s in enumerate(data["steps"]) if s["op"] == op)


def test_operation_catalog_is_closed():
    assert {op.value for op in Operation} == {
        "parse_number",
        "apply_discounts",
        "strip_vat",
        "per_unit",
        "map_values",
        "constant",
        "normalize_text",
    }


def test_golden_plan_parses_into_typed_model():
    plan = parse_plan(golden_plan_dict())

    assert plan.contract_version == "1"
    assert plan.engine_version == "0.1.0"
    assert plan.supplier == "Ferretería Ejemplo"
    assert plan.rounding.decimals == 2
    assert plan.rounding.mode == "half_up"
    assert plan.confirmations == ("C incluye IVA", "C es precio por caja", "moneda ARS")
    assert plan.steps == (
        NormalizeText(ColumnRef(0, "Código"), TargetField.SUPPLIER_CODE),
        NormalizeText(ColumnRef(1, "Descripción"), TargetField.DESCRIPTION),
        ParseNumber(ColumnRef(2, "Precio x caja c/IVA"), ",", "."),
        ApplyDiscounts(ColumnDiscounts(ColumnRef(4, "Bonif."), "plus_separated")),
        MapValues(
            ColumnRef(5, "IVA"),
            {"21%": Decimal("21"), "10,5%": Decimal("10.5")},
            TargetField.VAT_RATE,
        ),
        StripVat(FromField(TargetField.VAT_RATE)),
        PerUnit(FromColumn(ColumnRef(3, "Unid x caja"))),
        Constant(TargetField.CURRENCY, "ARS"),
    )


def test_float_literals_become_exact_decimals():
    plan = parse_plan(golden_plan_dict())
    map_step = next(s for s in plan.steps if isinstance(s, MapValues))
    assert map_step.table["10,5%"] == Decimal("10.5")


def test_constant_sources_are_accepted():
    data = golden_plan_dict()
    data["steps"][3] = {"op": "apply_discounts", "from": {"constant": [10, 5]}}
    data["steps"][5] = {"op": "strip_vat", "rate_from": {"constant": 21}}
    data["steps"][6] = {"op": "per_unit", "units_from": {"constant": 12}}

    plan = parse_plan(data)

    assert plan.steps[3] == ApplyDiscounts(ConstantDiscounts((Decimal(10), Decimal(5))))
    assert plan.steps[5] == StripVat(FromConstant(Decimal(21)))
    assert plan.steps[6] == PerUnit(FromConstant(Decimal(12)))


def test_confirmations_are_optional():
    data = golden_plan_dict()
    del data["confirmed_by_user"]
    assert parse_plan(data).confirmations == ()


def test_plan_without_discounts_vat_and_pack_steps_is_valid():
    data = golden_plan_dict()
    data["steps"] = [
        s
        for s in data["steps"]
        if s["op"] not in {"apply_discounts", "strip_vat", "per_unit", "map_values"}
    ]
    assert len(parse_plan(data).steps) == 4


# --- rejection classes -----------------------------------------------------


def test_non_dict_input_is_rejected():
    assert problems_for([1, 2, 3])


def test_unknown_operation_is_rejected():
    data = golden_plan_dict()
    data["steps"].append({"op": "eval", "expression": "price * 2"})
    problems = problems_for(data)
    assert any("unknown operation 'eval'" in p for p in problems)


def test_missing_op_is_rejected():
    data = golden_plan_dict()
    data["steps"].append({"column": {"index": 0, "header": "x"}})
    assert any("missing 'op'" in p for p in problems_for(data))


def test_missing_parameter_is_rejected():
    data = golden_plan_dict()
    del data["steps"][2]["decimal_sep"]
    assert any("missing parameter 'decimal_sep'" in p for p in problems_for(data))


def test_extra_parameter_is_rejected():
    data = golden_plan_dict()
    data["steps"][2]["formula"] = "x * 2"
    assert any("unexpected parameter 'formula'" in p for p in problems_for(data))


def test_extra_top_level_key_is_rejected():
    data = golden_plan_dict()
    data["script"] = "import os"
    assert any("unexpected key 'script'" in p for p in problems_for(data))


def test_missing_top_level_key_is_rejected():
    data = golden_plan_dict()
    del data["supplier"]
    assert any("missing key 'supplier'" in p for p in problems_for(data))


def test_unsupported_contract_version_is_rejected():
    data = golden_plan_dict()
    data["contract_version"] = "99"
    assert any("contract_version" in p for p in problems_for(data))


@pytest.mark.parametrize(
    "bad_column",
    [
        {"index": -1, "header": "x"},
        {"index": "2", "header": "x"},
        {"index": True, "header": "x"},
        {"index": 1, "header": ""},
        {"index": 1},
        {"header": "x"},
        {"index": 1, "header": "x", "extra": 1},
        "C",
    ],
)
def test_invalid_column_reference_is_rejected(bad_column):
    data = golden_plan_dict()
    data["steps"][2]["column"] = bad_column
    assert any("steps[2].column" in p for p in problems_for(data))


def test_decimal_and_thousands_separator_must_differ():
    data = golden_plan_dict()
    data["steps"][2]["decimal_sep"] = ","
    data["steps"][2]["thousands_sep"] = ","
    assert any("must differ" in p for p in problems_for(data))


def test_invalid_thousands_separator_is_rejected():
    data = golden_plan_dict()
    data["steps"][2]["thousands_sep"] = "'"
    assert any("thousands_sep" in p for p in problems_for(data))


def test_invalid_decimal_separator_is_rejected():
    data = golden_plan_dict()
    data["steps"][2]["decimal_sep"] = ""
    assert any("decimal_sep" in p for p in problems_for(data))


def test_empty_thousands_separator_is_allowed():
    data = golden_plan_dict()
    data["steps"][2]["thousands_sep"] = ""
    parse_plan(data)


def test_cost_steps_out_of_order_are_rejected():
    data = golden_plan_dict()
    i, j = step_index(data, "strip_vat"), step_index(data, "apply_discounts")
    data["steps"][i], data["steps"][j] = data["steps"][j], data["steps"][i]
    assert any("order" in p for p in problems_for(data))


def test_duplicate_cost_step_is_rejected():
    data = golden_plan_dict()
    data["steps"].append(dict(data["steps"][step_index(data, "per_unit")]))
    assert any("more than once" in p for p in problems_for(data))


def test_plan_without_parse_number_is_rejected():
    data = golden_plan_dict()
    del data["steps"][step_index(data, "parse_number")]
    assert any("parse_number" in p for p in problems_for(data))


def test_plan_not_producing_required_field_is_rejected():
    data = golden_plan_dict()
    del data["steps"][step_index(data, "constant")]
    assert any("'currency'" in p for p in problems_for(data))


def test_strip_vat_from_field_requires_earlier_vat_rate_step():
    data = golden_plan_dict()
    del data["steps"][step_index(data, "map_values")]
    assert any("vat_rate" in p for p in problems_for(data))


@pytest.mark.parametrize("percent", [-1, 101, "abc", True, None])
def test_invalid_discount_percent_is_rejected(percent):
    data = golden_plan_dict()
    data["steps"][3] = {"op": "apply_discounts", "from": {"constant": [10, percent]}}
    assert any("steps[3]" in p for p in problems_for(data))


def test_unknown_discount_format_is_rejected():
    data = golden_plan_dict()
    data["steps"][3]["from"]["format"] = "slash_separated"
    assert any("format" in p for p in problems_for(data))


def test_value_source_must_have_exactly_one_key():
    data = golden_plan_dict()
    data["steps"][5] = {
        "op": "strip_vat",
        "rate_from": {"constant": 21, "field": "vat_rate"},
    }
    assert any("steps[5].rate_from" in p for p in problems_for(data))


def test_constant_units_must_be_positive():
    data = golden_plan_dict()
    data["steps"][6] = {"op": "per_unit", "units_from": {"constant": 0}}
    assert any("steps[6]" in p for p in problems_for(data))


def test_normalize_text_target_must_be_a_text_field():
    data = golden_plan_dict()
    data["steps"][0]["to"] = "unit_cost_net"
    assert any("steps[0].to" in p for p in problems_for(data))


def test_unknown_target_field_is_rejected():
    data = golden_plan_dict()
    data["steps"][7]["field"] = "price"
    assert any("steps[7].field" in p for p in problems_for(data))


def test_map_values_table_must_not_be_empty():
    data = golden_plan_dict()
    data["steps"][4]["table"] = {}
    assert any("steps[4].table" in p for p in problems_for(data))


def test_vat_rate_constant_must_be_numeric():
    data = golden_plan_dict()
    data["steps"][7] = {"op": "constant", "field": "vat_rate", "value": "alta"}
    assert any("steps[7].value" in p for p in problems_for(data))


@pytest.mark.parametrize(
    "rounding",
    [
        {"decimals": 2, "mode": "banker"},
        {"decimals": -1, "mode": "half_up"},
        {"decimals": "2", "mode": "half_up"},
        {"decimals": 2},
        {"decimals": 2, "mode": "half_up", "extra": 1},
    ],
)
def test_invalid_rounding_is_rejected(rounding):
    data = golden_plan_dict()
    data["rounding"] = rounding
    assert any("rounding" in p for p in problems_for(data))


def test_confirmations_must_be_strings():
    data = golden_plan_dict()
    data["confirmed_by_user"] = ["ok", 3]
    assert any("confirmed_by_user" in p for p in problems_for(data))


def test_all_problems_are_collected_not_just_the_first():
    data = golden_plan_dict()
    data["steps"][2]["decimal_sep"] = ","
    data["steps"][2]["thousands_sep"] = ","
    data["steps"].append({"op": "eval"})
    data["rounding"] = {"decimals": 2, "mode": "banker"}
    data["unknown"] = 1

    assert len(problems_for(data)) >= 4


@pytest.mark.parametrize("junk", [["x"], {"a": 1}, None, 3.5])
def test_non_string_junk_in_enumerated_params_is_rejected_not_crashing(junk):
    data = golden_plan_dict()
    data["steps"][2]["decimal_sep"] = junk
    data["steps"][2]["thousands_sep"] = junk
    data["steps"][3]["from"]["format"] = junk
    data["rounding"]["mode"] = junk
    data["contract_version"] = junk
    data["steps"].append({"op": junk})

    assert len(problems_for(data)) >= 5


@pytest.mark.parametrize(
    "table",
    [
        {"U$S": 21, "u$s": 10.5},
        {"Dolar  Blue": 21, "dolar blue": 10.5},
        {"a b": 21, " A B ": 10.5},
    ],
)
def test_map_values_rejects_keys_that_collide_after_normalization(table):
    data = golden_plan_dict()
    data["steps"][4]["table"] = table
    found = [p for p in problems_for(data) if "steps[4].table" in p and "collide" in p]
    assert found
    assert all(repr(key) in found[0] for key in table)


def test_map_values_accepts_distinct_normalized_keys():
    data = golden_plan_dict()
    data["steps"][4]["table"] = {"21%": 21, "10,5%": 10.5, "0%": 0}
    assert parse_plan(data).steps[4].table["0%"] == 0


# -- serialization ----------------------------------------------------------------


def test_plan_to_dict_round_trips_through_parse_plan():
    plan = parse_plan(golden_plan_dict())
    data = plan_to_dict(plan)
    assert parse_plan(data) == plan
    assert json.loads(json.dumps(data)) == data  # plain JSON types only


def test_plan_to_dict_keeps_decimal_digits_exactly():
    data = golden_plan_dict()
    data["steps"][4]["table"] = {"21%": "21.50", "10,5%": "0.10"}
    data["steps"][3] = {"op": "apply_discounts", "from": {"constant": ["10.0", "5"]}}
    plan = parse_plan(data)
    back = parse_plan(plan_to_dict(plan))
    assert [str(v) for v in back.steps[4].table.values()] == ["21.50", "0.10"]
    assert [str(p) for p in back.steps[3].source.percents] == ["10.0", "5"]


def test_plan_to_dict_covers_every_step_kind():
    data = golden_plan_dict()
    data["steps"][3] = {"op": "apply_discounts", "from": {"constant": [10]}}
    data["steps"][6] = {"op": "per_unit", "units_from": {"constant": 12}}
    data["steps"].append({"op": "constant", "field": "units_per_pack", "value": 12})
    plan = parse_plan(data)
    assert parse_plan(plan_to_dict(plan)) == plan
