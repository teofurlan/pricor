"""Shared fixtures: the example plan from the operations note (section 3)."""

import copy

GOLDEN_HEADERS = [
    "Código",
    "Descripción",
    "Precio x caja c/IVA",
    "Unid x caja",
    "Bonif.",
    "IVA",
]


def golden_plan_dict() -> dict:
    return copy.deepcopy(
        {
            "contract_version": "1",
            "engine_version": "0.1.0",
            "supplier": "Ferretería Ejemplo",
            "steps": [
                {
                    "op": "normalize_text",
                    "column": {"index": 0, "header": "Código"},
                    "to": "supplier_code",
                },
                {
                    "op": "normalize_text",
                    "column": {"index": 1, "header": "Descripción"},
                    "to": "description",
                },
                {
                    "op": "parse_number",
                    "column": {"index": 2, "header": "Precio x caja c/IVA"},
                    "decimal_sep": ",",
                    "thousands_sep": ".",
                },
                {
                    "op": "apply_discounts",
                    "from": {
                        "column": {"index": 4, "header": "Bonif."},
                        "format": "plus_separated",
                    },
                },
                {
                    "op": "map_values",
                    "column": {"index": 5, "header": "IVA"},
                    "table": {"21%": 21, "10,5%": 10.5},
                    "to": "vat_rate",
                },
                {"op": "strip_vat", "rate_from": {"field": "vat_rate"}},
                {
                    "op": "per_unit",
                    "units_from": {"column": {"index": 3, "header": "Unid x caja"}},
                },
                {"op": "constant", "field": "currency", "value": "ARS"},
            ],
            "rounding": {"decimals": 2, "mode": "half_up"},
            "confirmed_by_user": ["C incluye IVA", "C es precio por caja", "moneda ARS"],
        }
    )
