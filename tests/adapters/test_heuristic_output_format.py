import pytest

from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.ports.output_format import OUTPUT_FIELDS, TemplateColumn


@pytest.mark.parametrize(("header", "field"), [
    ("Código proveedor", "supplier_code"), ("SKU", "supplier_code"),
    ("Descripción", "description"), ("Costo neto", "unit_cost_net"),
    ("Moneda", "currency"), ("IVA", "vat_rate"),
    ("Unidades por bulto", "units_per_pack"), ("EAN", "barcode"),
    ("Precio sugerido", "suggested_retail_price"),
    ("Costo convertido", "unit_cost_net_converted"),
    ("Tipo de cambio", "fx_rate"), ("Fuente cambio", "fx_source"),
    ("Fecha cambio", "fx_date"), ("Fila origen", "source_row"),
    *[(name, name) for name in OUTPUT_FIELDS],
])
def test_headers_propose_closed_fields(header, field):
    proposal, = HeuristicOutputFormat().propose((TemplateColumn(0, header, ()),))
    assert proposal.source == f"field:{field}"
    assert proposal.proposed_by == "heuristics"
    assert 0 <= proposal.confidence <= 1


def test_unmatched_columns_are_empty_and_duplicate_fields_are_allowed():
    columns = tuple(TemplateColumn(i, name, ()) for i, name in enumerate(("SKU", "SKU", "Stock")))
    assert [p.source for p in HeuristicOutputFormat().propose(columns)] == [
        "field:supplier_code", "field:supplier_code", "empty",
    ]
