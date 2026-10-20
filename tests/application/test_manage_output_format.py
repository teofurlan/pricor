import io

import pytest
from openpyxl import Workbook

from pricor.adapters.gemma_output_format import GemmaOutputFormat
from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.errors import InvalidInputError
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.ports.model_errors import ModelUnavailableError
from pricor.ports.output_format import OutputFormatNotFoundError
from pricor.ports.spreadsheet import SpreadsheetError

from ..adapters.test_gemma_output_format import Chat, reply


@pytest.fixture
def manager():
    db = SqliteDatabase(":memory:")
    yield ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    db.close()


def template(tmp_path, suffix="csv"):
    path = tmp_path / f"template.{suffix}"
    rows = [[None, None, None], ["SKU", None, "Note"], *[[f"00{i}", i, None] for i in range(7)]]
    if suffix == "csv":
        import csv
        buffer = io.StringIO()
        csv.writer(buffer).writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    else:
        book = Workbook()
        book.active.title = "Template"
        for row in rows:
            book.active.append(row)
        book.save(path)
    return path


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_upload_reads_first_nonempty_header_and_five_following_samples(manager, tmp_path, suffix):
    result = manager.upload(template(tmp_path, suffix))
    assert result.name == f"template.{suffix}"
    assert result.state == "proposed"
    assert [c.index for c in result.columns] == [0, 1, 2]
    assert [c.name for c in result.columns] == ["SKU", "Column 2", "Note"]
    assert [c.samples for c in result.columns] == [tuple(f"00{i}" for i in range(5)), tuple(str(i) for i in range(5)), ("",) * 5]
    assert [c.source for c in result.columns] == [None] * 3
    assert manager.get() == result


@pytest.mark.parametrize("error", [False, True])
def test_invalid_or_unavailable_gemma_falls_back_to_heuristics(tmp_path, error):
    db = SqliteDatabase(":memory:")
    chat = Chat(reply("field:not_allowed"), ModelUnavailableError("offline") if error else None)
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat(), GemmaOutputFormat(chat))
    result = manager.upload(template(tmp_path))
    assert result.columns[0].proposal.source == "field:supplier_code"
    assert all(c.proposal.proposed_by == "heuristics" and c.source is None for c in result.columns)
    assert len(chat.calls) == 1
    db.close()


def test_confirm_requires_every_source_and_keeps_proposal(manager, tmp_path):
    proposed = manager.upload(template(tmp_path))
    sources = ["field:supplier_code", "empty", "constant:001"]
    confirmed = manager.confirm(sources)
    assert confirmed.state == "confirmed"
    assert [c.source for c in confirmed.columns] == sources
    assert [c.proposal for c in confirmed.columns] == [c.proposal for c in proposed.columns]
    assert manager.get() == confirmed
    manager.delete()
    with pytest.raises(OutputFormatNotFoundError):
        manager.get()


@pytest.mark.parametrize("sources", [[], ["empty"], ["empty"] * 4,
    ["field:nope", "empty", "empty"], ["constant:", "empty", "empty"],
    ["constant:   ", "empty", "empty"], ["constant:" + "x" * 201, "empty", "empty"],
    ["eval:1+1", "empty", "empty"], [None, "empty", "empty"],
])
def test_rejected_confirmation_never_replaces_stored_format(manager, tmp_path, sources):
    manager.upload(template(tmp_path))
    before = manager.confirm(["empty"] * 3)
    with pytest.raises(InvalidInputError):
        manager.confirm(sources)
    assert manager.get() == before


@pytest.mark.parametrize("length", [1, 200])
def test_constant_length_boundaries(manager, tmp_path, length):
    manager.upload(template(tmp_path))
    assert manager.confirm(["constant:" + "x" * length, "empty", "empty"]).state == "confirmed"


def test_upload_replaces_confirmed_format_but_failed_upload_does_not(manager, tmp_path):
    path = template(tmp_path)
    manager.upload(path)
    before = manager.confirm(["empty"] * 3)
    empty = tmp_path / "empty.csv"
    empty.write_text("\n,,\n", encoding="utf-8")
    with pytest.raises(SpreadsheetError):
        manager.upload(empty)
    assert manager.get() == before
    replacement = manager.upload(path)
    assert replacement.state == "proposed" and all(c.source is None for c in replacement.columns)


def test_missing_format_is_not_found_for_read_and_confirm(manager):
    with pytest.raises(OutputFormatNotFoundError):
        manager.get()
    with pytest.raises(OutputFormatNotFoundError):
        manager.confirm(["empty"])


def test_explicit_sheet_selection_and_single_column(manager, tmp_path):
    path = tmp_path / "sheets.xlsx"
    book = Workbook()
    book.active.append(["Wrong"])
    sheet = book.create_sheet("Chosen")
    sheet.append(["My only field"])
    sheet.append(["sample"])
    book.save(path)
    result = manager.upload(path, "Chosen")
    assert [(c.name, c.samples) for c in result.columns] == [("My only field", ("sample",))]


def test_define_by_hand_confirms_exactly_those_columns_in_order(manager):
    result = manager.define([("Código", "field:supplier_code", None), ("Rubro", "constant:Ferretería", None), ("Nota", "empty", None)])
    assert result.state == "confirmed"
    assert result.name == ""
    assert [(c.index, c.name, c.source, c.samples) for c in result.columns] == [
        (0, "Código", "field:supplier_code", ()),
        (1, "Rubro", "constant:Ferretería", ()),
        (2, "Nota", "empty", ()),
    ]
    assert all(c.proposal.proposed_by == "user" and c.proposal.confidence == 1.0 for c in result.columns)
    assert manager.get() == result


def test_define_keeps_template_samples_for_linked_columns_and_allows_renames(manager, tmp_path):
    uploaded = manager.upload(template(tmp_path))
    result = manager.define([("Extra", "empty", None), ("Code", "field:supplier_code", 0)])
    assert result.name == uploaded.name
    assert [c.name for c in result.columns] == ["Extra", "Code"]
    assert result.columns[0].samples == ()
    assert result.columns[1].samples == uploaded.columns[0].samples
    assert result.columns[1].proposal == uploaded.columns[0].proposal


@pytest.mark.parametrize("columns, message", [
    ([], "at least one column"),
    ([("  ", "empty", None)], "name"),
    ([("A" * 101, "empty", None)], "name"),
    ([("SKU", "empty", None), ("sku ", "empty", None)], "unique"),
    ([("SKU", "field:nope", None)], "source"),
    ([("SKU", "empty", 7)], "template column"),
])
def test_define_rejects_invalid_columns_and_keeps_the_stored_format(manager, columns, message):
    stored = manager.define([("SKU", "field:supplier_code", None)])
    with pytest.raises(InvalidInputError, match=message):
        manager.define(columns)
    assert manager.get() == stored


def test_a_stray_cell_below_the_samples_adds_no_column(manager, tmp_path):
    path = tmp_path / "stray.csv"
    rows = ["SKU,Costo", *[f"00{i},{i}" for i in range(5)], "", ",,,,,,,,nota suelta"]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert [column.name for column in manager.upload(path).columns] == ["SKU", "Costo"]


def test_sample_rows_still_widen_the_template(manager, tmp_path):
    path = tmp_path / "wide.csv"
    path.write_text("SKU,Costo\n001,2,extra\n", encoding="utf-8")
    assert [column.name for column in manager.upload(path).columns] == ["SKU", "Costo", "Column 3"]
