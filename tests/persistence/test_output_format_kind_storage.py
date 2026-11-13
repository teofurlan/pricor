import json

from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.ports.output_format import OutputColumn, OutputFormat, OutputProposal


def test_a_format_stored_without_kind_reads_as_legacy_none():
    db = SqliteDatabase(":memory:")
    legacy = {"name": "old.csv", "state": "confirmed", "columns": [{
        "index": 0, "name": "SKU", "samples": ["1"],
        "proposal": {"source": "field:supplier_code", "proposed_by": "heuristics", "confidence": 0.9},
        "source": "field:supplier_code",
    }]}
    with db.transaction() as connection:
        connection.execute("insert into output_format (id, data) values (1, ?)", (json.dumps(legacy),))
    loaded = db.output_format.get()
    assert [column.kind for column in loaded.columns] == [None]
    db.close()


def test_kind_survives_a_round_trip():
    db = SqliteDatabase(":memory:")
    column = OutputColumn(0, "Precio", (), OutputProposal("field:unit_cost_net", "user", 1.0), "field:unit_cost_net", "price")
    db.output_format.save(OutputFormat("", "confirmed", (column,)))
    assert db.output_format.get().columns[0].kind == "price"
    db.close()
