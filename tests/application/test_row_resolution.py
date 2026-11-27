import pytest

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.application.errors import InvalidInputError, InvalidOperationError
from pricor.application.export_import import ExportImport
from pricor.application.import_first_time import ClassifierStage, ImportFirstTime
from pricor.domain.roles import ColumnRole as R
from pricor.ports.import_session import SessionStatus

from .fakes import FakeClassifier, FakeReader

HEADER = ("Codigo", "Descripcion", "Precio lista", "IVA")
ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Precio lista": (R.COST_PRICE, 0.9),
    "IVA": (R.VAT_RATE, 0.9),
}
ROWS = [
    ("LISTA OCTUBRE", None, None, None),  # row 1: preamble
    HEADER,  # row 2: header
    ("A1", "Tornillo", "1.210,00", "21%"),  # row 3: accepted
    ("CAT-1", "GRUPO AUTOMOVIL", "", "21%"),  # row 4: rejected (empty price)
    ("A2", "Tuerca", "968,00", "21%"),  # row 5: accepted
    ("CAT-2", "GRUPO HOGAR", "", "21%"),  # row 6: rejected (empty price)
    ("A3", "Arandela", "bad-num", "21%"),  # row 7: rejected (invalid number)
    ("A4", "Clavo", "60,50", "21%"),  # row 8: accepted
]


def _ready_session(rows=ROWS):
    repo = InMemoryImportSessionRepository()
    use_case = ImportFirstTime(
        FakeReader(rows),
        repo,
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
        id_factory=iter("abcdef").__next__,
    )
    session = use_case.start("lista.xlsx", "Ferreteria Ejemplo")
    session = use_case.answer(session.id, "number_format", "decimal_comma")
    session = use_case.answer(session.id, "price_includes_vat", "yes")
    session = use_case.answer(session.id, "currency", "ARS")
    assert session.status is SessionStatus.READY_FOR_PREVIEW
    return use_case, session


def test_row_context_returns_surrounding_rows_and_failing_column_indexes():
    use_case, session = _ready_session()
    ctx = use_case.row_context(session.id, 4, radius=2)

    assert ctx["row_number"] == 4
    assert ctx["headers"] == ["Codigo", "Descripcion", "Precio lista", "IVA"]
    assert ctx["target_columns"] == [2]
    assert [entry["row_number"] for entry in ctx["rows"]] == [2, 3, 4, 5, 6]
    target = next(entry for entry in ctx["rows"] if entry["is_target"])
    assert target["cells"] == ["CAT-1", "GRUPO AUTOMOVIL", "", "21%"]
    assert target["ignored"] is False


def test_row_context_clamps_to_sheet_boundaries_and_validates_inputs():
    use_case, session = _ready_session()
    ctx = use_case.row_context(session.id, 1, radius=2)
    assert [entry["row_number"] for entry in ctx["rows"]] == [1, 2, 3]

    with pytest.raises(InvalidInputError):
        use_case.row_context(session.id, 0)
    with pytest.raises(InvalidInputError):
        use_case.row_context(session.id, len(ROWS) + 1)
    with pytest.raises(InvalidInputError):
        use_case.row_context(session.id, 3, radius=6)


def test_ignore_by_reason_and_restore_ignored_update_totals_and_preview():
    use_case, session = _ready_session()
    before = use_case.preview(session.id).totals
    assert (before["accepted"], before["rejected"]) == (3, 3)

    # Identify exact empty-price reason from row 4
    row4 = next(item for item in use_case.preview(session.id).items if item.row_number == 4)
    empty_reason = row4.reasons[0]

    res = use_case.resolve_rows(session.id, "ignore_by_reason", reason=empty_reason)
    assert res["affected"] == 2
    assert res["ignored_count"] == 2
    assert (res["totals"]["accepted"], res["totals"]["rejected"]) == (3, 1)
    assert res["totals"]["skipped_rows"]["ignored_by_user"] == 2

    restored = use_case.resolve_rows(session.id, "restore_ignored")
    assert restored["affected"] == 2
    assert restored["ignored_count"] == 0
    assert (restored["totals"]["accepted"], restored["totals"]["rejected"]) == (3, 3)
    assert "ignored_by_user" not in restored["totals"]["skipped_rows"]


def test_edit_cell_and_edit_by_reason_fix_rejected_rows_through_approval_and_export():
    use_case, session = _ready_session()
    # Edit row 7's invalid price directly
    res_one = use_case.resolve_rows(
        session.id, "edit_cell", row_number=7, column_index=2, value="121,00"
    )
    assert res_one["affected"] == 1
    assert (res_one["totals"]["accepted"], res_one["totals"]["rejected"]) == (4, 2)

    # Edit both remaining empty-price rows by reason
    row4 = next(item for item in use_case.preview(session.id).items if item.row_number == 4)
    res_batch = use_case.resolve_rows(
        session.id, "edit_by_reason", reason=row4.reasons[0], column_index=2, value="242,00"
    )
    assert res_batch["affected"] == 2
    assert (res_batch["totals"]["accepted"], res_batch["totals"]["rejected"]) == (6, 0)

    # Ignore row 6 instead, approve, and check ExportImport only exports accepted non-ignored rows
    use_case.resolve_rows(session.id, "ignore_row", row_number=6)
    approved = use_case.approve(session.id)
    assert len(approved.approved_result.accepted) == 5
    assert len(approved.approved_result.rejected) == 0

    from pricor.adapters.csv_exporter import CsvExporter
    from pricor.adapters.xlsx_exporter import XlsxExporter

    exported = ExportImport(use_case.get, [CsvExporter(), XlsxExporter()]).products(session.id, "csv")
    csv_text = exported.content.decode("utf-8")
    assert "A3" in csv_text
    assert "CAT-1" in csv_text
    assert "CAT-2" not in csv_text


def test_approved_session_refuses_resolve_rows_and_choose_header_resets_resolutions():
    use_case, session = _ready_session()
    use_case.resolve_rows(session.id, "ignore_row", row_number=4)
    use_case.resolve_rows(session.id, "edit_cell", row_number=7, column_index=2, value="121,00")

    # Changing header resets ignored_rows and cell_overrides
    reopened = use_case.choose_header(session.id, 1)
    assert reopened.ignored_rows == set()
    assert reopened.cell_overrides == {}

    use_case.answer(session.id, "number_format", "decimal_comma")
    use_case.answer(session.id, "price_includes_vat", "yes")
    use_case.answer(session.id, "currency", "ARS")
    use_case.approve(session.id)

    with pytest.raises(InvalidOperationError):
        use_case.resolve_rows(session.id, "ignore_row", row_number=4)
