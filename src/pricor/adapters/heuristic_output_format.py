"""Conservative header-keyword proposals when Gemma cannot propose a format."""

from collections.abc import Sequence

from pricor.adapters.heuristic_classifier import normalize_header
from pricor.ports.output_format import OUTPUT_FIELDS, OutputProposal, TemplateColumn

_ALIASES = {
    "supplier_code": ("sku", "code", "codigo", "codigo proveedor", "cod prov"),
    "description": ("descripcion", "detalle", "producto", "nombre"),
    "unit_cost_net": ("costo", "costo neto", "precio", "precio neto", "net cost"),
    "currency": ("moneda", "divisa"),
    "vat_rate": ("iva", "alicuota", "vat"),
    "units_per_pack": ("unidades por bulto", "unidades por pack", "uxb", "pack"),
    "barcode": ("ean", "gtin", "codigo de barras", "codigo barras"),
    "suggested_retail_price": ("precio sugerido", "precio venta", "pvp", "retail price"),
    "unit_cost_net_converted": ("costo convertido", "precio convertido", "converted cost"),
    "fx_rate": ("tipo de cambio", "exchange rate", "cotizacion"),
    "fx_source": ("fuente cambio", "fuente tipo de cambio", "exchange rate source"),
    "fx_date": ("fecha cambio", "fecha tipo de cambio", "exchange rate date"),
    "source_row": ("fila origen", "fila", "source row"),
}
_HEADERS = {
    normalize_header(alias): name
    for name in OUTPUT_FIELDS
    for alias in (name, *_ALIASES[name])
}


class HeuristicOutputFormat:
    def propose(self, columns: Sequence[TemplateColumn]) -> tuple[OutputProposal, ...]:
        proposals = []
        for column in columns:
            field = _HEADERS.get(normalize_header(column.name))
            proposals.append(OutputProposal(
                f"field:{field}" if field else "empty", "heuristics", 0.9 if field else 0.0
            ))
        return tuple(proposals)
