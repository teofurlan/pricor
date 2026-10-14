"""Sample export views for the exporter tests."""

from decimal import Decimal

from pricor.domain.contract import ContractRecord
from pricor.ports.exporter import ImportExport, RejectedEntry
from pricor.ports.price_history import ImportedRecord

FULL = ContractRecord(
    "00123",
    'Tornillo 1/4", cabeza "plana"\nx100',
    Decimal("855.00"),
    "ARS",
    vat_rate=Decimal("10.5"),
    units_per_pack=Decimal("12"),
    barcode="0779123456789",
    suggested_retail_price=Decimal("1234.50"),
)
BARE = ContractRecord("A2", "Tuerca", Decimal("0.1"), "USD")


def sample(accepted=None, rejected=None, headers=("Codigo", "Descripcion", "Precio")):
    return ImportExport(
        "Ferreteria Ejemplo",
        tuple(accepted if accepted is not None else [ImportedRecord(3, FULL), ImportedRecord(8, BARE)]),
        tuple(
            rejected
            if rejected is not None
            else [
                RejectedEntry(5, ("A9", "Brida", "abc"), ("Precio: not a number",)),
                RejectedEntry(6, ("", "Sin codigo", "10,00"), ("supplier_code is empty", "x")),
            ]
        ),
        tuple(headers),
    )
