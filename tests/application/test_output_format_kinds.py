import pytest

from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.errors import InvalidInputError
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.ports.output_format import OUTPUT_KINDS, default_kind


@pytest.mark.parametrize("source,kind", [
    ("field:description", "description"), ("field:supplier_code", "code"), ("field:barcode", "code"),
    ("field:unit_cost_net", "price"), ("field:suggested_retail_price", "price"),
    ("field:unit_cost_net_converted", "price"), ("field:vat_rate", "number"),
    ("field:units_per_pack", "number"), ("field:fx_rate", "number"), ("field:source_row", "number"),
    ("field:currency", "text"), ("field:fx_source", "text"), ("field:fx_date", "text"),
    ("empty", "text"), ("constant:1", "text"),
])
def test_default_kind(source, kind):
    assert default_kind(source) == kind


def test_vocabulary():
    assert OUTPUT_KINDS == ("text", "description", "code", "number", "price")


@pytest.fixture
def manager():
    db = SqliteDatabase(":memory:")
    yield ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    db.close()


def test_define_defaults_validates_and_accepts_explicit_kinds(manager):
    result = manager.define([
        ("A", "field:unit_cost_net", None), ("B", "field:unit_cost_net", None, "text"),
        ("C", "constant:3,5", None, "price"),
    ])
    assert [c.kind for c in result.columns] == ["price", "text", "price"]
    with pytest.raises(InvalidInputError):
        manager.define([("A", "empty", None, "bogus")])
    with pytest.raises(InvalidInputError):
        manager.define([("A", "constant:abc", None, "number")])
    assert [c.kind for c in manager.get().columns] == ["price", "text", "price"]
