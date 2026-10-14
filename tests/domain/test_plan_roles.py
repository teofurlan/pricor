from pricor.domain.plan import parse_plan
from pricor.domain.plan_roles import column_roles
from pricor.domain.roles import ColumnRole as R


def ref(index, header):
    return {"index": index, "header": header}


def plan_with(*steps):
    return parse_plan(
        {
            "contract_version": "1",
            "engine_version": "test",
            "supplier": "Ferreteria",
            "steps": [
                {"op": "normalize_text", "column": ref(0, "Codigo"), "to": "supplier_code"},
                {"op": "normalize_text", "column": ref(1, "Descripcion"), "to": "description"},
                {
                    "op": "parse_number",
                    "column": ref(2, "Precio"),
                    "decimal_sep": ",",
                    "thousands_sep": ".",
                },
                *steps,
                {"op": "constant", "field": "currency", "value": "ARS"},
            ],
            "rounding": {"decimals": 2, "mode": "half_up"},
        }
    )


def test_core_columns_get_their_roles():
    assert column_roles(plan_with()) == {0: R.CODE, 1: R.DESCRIPTION, 2: R.COST_PRICE}


def test_optional_columns_get_their_roles():
    plan = plan_with(
        {"op": "apply_discounts", "from": {"column": ref(3, "Dto"), "format": "plus_separated"}},
        {"op": "strip_vat", "rate_from": {"column": ref(4, "IVA")}},
        {"op": "per_unit", "units_from": {"column": ref(5, "Bulto")}},
    )

    assert column_roles(plan) == {
        0: R.CODE,
        1: R.DESCRIPTION,
        2: R.COST_PRICE,
        3: R.DISCOUNT,
        4: R.VAT_RATE,
        5: R.UNITS_PER_PACK,
    }


def test_barcode_and_mapped_columns_get_their_roles():
    plan = plan_with(
        {"op": "normalize_text", "column": ref(3, "EAN"), "to": "barcode"},
        {"op": "map_values", "column": ref(4, "Alicuota"), "table": {"21%": "21"}, "to": "vat_rate"},
        {"op": "strip_vat", "rate_from": {"field": "vat_rate"}},
    )

    roles = column_roles(plan)

    assert roles[3] is R.BARCODE
    assert roles[4] is R.VAT_RATE


def test_constants_do_not_reference_columns():
    plan = plan_with(
        {"op": "apply_discounts", "from": {"constant": ["10", "5"]}},
        {"op": "strip_vat", "rate_from": {"constant": "21"}},
        {"op": "per_unit", "units_from": {"constant": "12"}},
    )

    assert set(column_roles(plan)) == {0, 1, 2}


def test_the_mapped_currency_column_is_the_currency_role():
    plan = parse_plan(
        {
            "contract_version": "1",
            "engine_version": "test",
            "supplier": "Ferreteria",
            "steps": [
                {"op": "normalize_text", "column": ref(0, "Codigo"), "to": "supplier_code"},
                {"op": "normalize_text", "column": ref(1, "Descripcion"), "to": "description"},
                {
                    "op": "parse_number",
                    "column": ref(2, "Precio"),
                    "decimal_sep": ".",
                    "thousands_sep": "",
                },
                {"op": "map_values", "column": ref(3, "Moneda"), "table": {"$": "ARS"}, "to": "currency"},
            ],
            "rounding": {"decimals": 2, "mode": "half_up"},
        }
    )

    assert column_roles(plan)[3] is R.CURRENCY
