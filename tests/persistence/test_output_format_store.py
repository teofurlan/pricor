from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.manage_output_format import ManageOutputFormat


def test_proposal_confirmation_replacement_and_deletion_survive_reopening(tmp_path):
    path = tmp_path / "store.db"
    template = tmp_path / "template.csv"
    template.write_text('SKU,Note\n001,"quoted, note"\n', encoding="utf-8")
    db = SqliteDatabase(path)
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    proposed = manager.upload(template)
    db.close()
    db = SqliteDatabase(path)
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    assert manager.get() == proposed
    confirmed = manager.confirm(["field:supplier_code", "constant:=do not execute"])
    db.close()
    db = SqliteDatabase(path)
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    assert manager.get() == confirmed
    replacement = tmp_path / "other.csv"
    replacement.write_text("Other\nexample\n", encoding="utf-8")
    uploaded = manager.upload(replacement)
    assert uploaded.name == "other.csv" and uploaded.state == "proposed"
    assert len(uploaded.columns) == 1 and uploaded.columns[0].source is None
    db.close()
    db = SqliteDatabase(path)
    assert db.output_format.get() == uploaded
    db.output_format.delete()
    db.close()
    db = SqliteDatabase(path)
    assert db.output_format.get() is None
    db.close()
