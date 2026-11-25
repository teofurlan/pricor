from pathlib import Path

from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.pdf_price_list_reader import PdfPriceListReader
from pricor.adapters.session_codec import decode, encode
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.import_first_time import ImportFirstTime
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.domain.roles import ColumnRole
from pricor.ports.chat_client import ChatReply

from ..adapters.pdf_fixtures import pdf_bytes


class FakeVisionClient:
    def __init__(self, replies):
        self._replies = list(replies)

    def chat_json_with_images(self, system, user, images, schema):
        return ChatReply(self._replies.pop(0), 0.1)


def test_digital_pdf_import_has_no_pdf_vision_notice(tmp_path):
    pdf = tmp_path / "lista.pdf"
    pdf.write_bytes(
        pdf_bytes(
            [
                [
                    ["Codigo", "Descripcion", "Precio Lista"],
                    ["001", "Tornillo 8x1", "100,00"],
                    ["002", "Tuerca M8", "50,00"],
                ]
            ]
        )
    )
    reader = FileSpreadsheetReader(pdf_reader=PdfPriceListReader())
    use_case = ImportFirstTime(
        reader,
        InMemoryImportSessionRepository(),
        [ClassifierStage("heuristics", HeuristicColumnClassifier(), 0.75)],
        None,
    )

    session = use_case.start(pdf, "Ferreteria Central")

    assert all(n.code != "pdf_vision_extracted" for n in session.notices)
    assert session.source_notices == ()


def test_vision_pdf_import_adds_and_preserves_notice_through_header_reuse_and_codec(tmp_path):
    pdf = tmp_path / "escaneado.pdf"
    pdf.write_bytes(pdf_bytes([["Codigo  Detalle  Precio"]]))
    vision = FakeVisionClient(
        [
            {
                "columns": ["Codigo", "Descripcion", "Precio Lista"],
                "rows": [
                    ["001", "Tornillo 8x1", "100,00"],
                    ["002", "Tuerca M8", "50,00"],
                ],
            }
        ]
    )
    reader = FileSpreadsheetReader(
        pdf_reader=PdfPriceListReader(vision_client=vision, page_renderer=lambda *_: [b"png"])
    )
    db = SqliteDatabase(":memory:")
    try:
        use_case = ReuseSupplierPlan(
            reader,
            db.sessions,
            [ClassifierStage("heuristics", HeuristicColumnClassifier(), 0.75)],
            None,
            plans=db.plans,
            approvals=db,
        )

        session = use_case.start(pdf, "Proveedor PDF")
        assert [n.code for n in session.notices] == ["pdf_vision_extracted"]

        # Survives choose_header + _classify
        session = use_case.choose_header(session.id, 0)
        assert [n.code for n in session.notices] == ["pdf_vision_extracted"]

        # Survives session_codec round-trip
        restored = decode(encode(session))
        assert [n.code for n in restored.notices] == ["pdf_vision_extracted"]
        assert [n.code for n in restored.source_notices] == ["pdf_vision_extracted"]

        # Finish and approve first import, then reuse on a second scanned PDF
        session = use_case.set_roles(
            session.id,
            {0: ColumnRole.CODE, 1: ColumnRole.DESCRIPTION, 2: ColumnRole.COST_PRICE},
        )
        session = use_case.answer(session.id, "price_includes_vat", "no")
        session = use_case.answer(session.id, "currency", "ARS")
        use_case.approve(session.id)

        vision._replies.append(
            {
                "columns": ["Codigo", "Descripcion", "Precio Lista"],
                "rows": [
                    ["001", "Tornillo 8x1", "110,00"],
                    ["002", "Tuerca M8", "55,00"],
                ],
            }
        )
        reused = use_case.start(pdf, "Proveedor PDF")
        assert [n.code for n in reused.notices] == ["pdf_vision_extracted"]
    finally:
        db.close()
