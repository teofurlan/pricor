from decimal import Decimal

from pricor.domain.contract import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    ContractRecord,
    TargetField,
)


def test_required_fields_are_the_four_core_fields():
    assert REQUIRED_FIELDS == frozenset(
        {
            TargetField.SUPPLIER_CODE,
            TargetField.DESCRIPTION,
            TargetField.UNIT_COST_NET,
            TargetField.CURRENCY,
        }
    )


def test_optional_fields_are_disjoint_from_required():
    assert OPTIONAL_FIELDS == frozenset(
        {
            TargetField.VAT_RATE,
            TargetField.UNITS_PER_PACK,
            TargetField.BARCODE,
            TargetField.SUGGESTED_RETAIL_PRICE,
        }
    )
    assert not (OPTIONAL_FIELDS & REQUIRED_FIELDS)


def test_record_keeps_codes_as_text_with_leading_zeros():
    record = ContractRecord(
        supplier_code="00123",
        description="Screw",
        unit_cost_net=Decimal("855.00"),
        currency="ARS",
        barcode="0779123456789",
    )
    assert record.supplier_code == "00123"
    assert record.barcode == "0779123456789"
    assert record.vat_rate is None
