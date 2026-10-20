"""An approved import keeps the products layout that was in force when it was approved."""

import csv
import io
import json

import pytest

from pricor.adapters.csv_exporter import CsvExporter
from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.session_codec import decode, encode
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.export_import import ExportImport
from pricor.application.manage_output_format import ManageOutputFormat

from ..persistence.sessions import Flow


@pytest.fixture
def formats():
    db = SqliteDatabase(":memory:")
    yield ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat()), db.output_format
    db.close()


def header(content: bytes) -> list[str]:
    return next(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def test_changing_the_format_after_approval_does_not_change_the_download(formats):
    manager, store = formats
    manager.define([("SKU", "field:supplier_code", None), ("Costo", "field:unit_cost_net", None)])
    flow = Flow(output_formats=store)
    session = flow.approved()
    exports = ExportImport(flow.use_case.get, [CsvExporter()], output_format=store)
    assert header(exports.products(session.id, "csv").content) == ["SKU", "Costo"]

    manager.define([("Otra", "empty", None)])
    assert header(exports.products(session.id, "csv").content) == ["SKU", "Costo"]
    manager.delete()
    assert header(exports.products(session.id, "csv").content) == ["SKU", "Costo"]


def test_an_import_approved_with_standard_columns_keeps_them(formats):
    manager, store = formats
    flow = Flow(output_formats=store)
    session = flow.approved()
    exports = ExportImport(flow.use_case.get, [CsvExporter()], output_format=store)
    standard = exports.products(session.id, "csv").content

    manager.define([("SKU", "field:supplier_code", None)])
    assert exports.products(session.id, "csv").content == standard


def test_a_proposed_format_is_not_frozen(formats, tmp_path):
    manager, store = formats
    path = tmp_path / "template.csv"
    path.write_text("SKU\n001\n", encoding="utf-8")
    manager.upload(path)  # proposed, not confirmed
    session = Flow(output_formats=store).approved()
    assert session.output_format_frozen and session.approved_output_format is None


def test_a_session_approved_before_formats_were_frozen_still_loads():
    document = json.loads(encode(Flow().approved()))
    for name in ("approved_output_format", "output_format_frozen"):
        document["f"].pop(name)
    restored = decode(json.dumps(document))
    assert (restored.approved_output_format, restored.output_format_frozen) == (None, False)


def test_the_frozen_format_round_trips_through_the_session_codec(formats):
    manager, store = formats
    manager.define([("SKU", "field:supplier_code", None)])
    session = Flow(output_formats=store).approved()
    restored = decode(encode(session))
    assert restored.approved_output_format == session.approved_output_format
    assert restored.output_format_frozen is True
