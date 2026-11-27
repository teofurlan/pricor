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

from ..adapters.pdf_fixtures import borderless_pdf_bytes, pdf_bytes


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


def test_borderless_digital_pdf_imports_without_vision_or_notice(tmp_path):
    pdf = tmp_path / "domitec.pdf"
    pdf.write_bytes(
        borderless_pdf_bytes(
            [
                [
                    (["LISTA DE PRECIOS VENTA SUELTOS"], False),
                    (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
                    (["GRUPO DE PRODUCTOS 01 - AUTOMOVIL"], False),
                    (["055170911", "DET CONC 2X10 LT LIMPIA MOTOR", "1286.26", "64.31"], False),
                    (["055152911", "DET CONC 3X4.5 LT SILICON", "2196.39", "81.34"], False),
                    (["069151999", "SOLO ENVASE SIN FRACCIONAR", "250.80", ""], False),
                    (["Usuario:CBOSCHI Fecha:11/01/2021 Item:2035"], False),
                ],
                [
                    (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
                    (["068152912", "CERA LIQUIDA 3X4.5 LTS NEGRA", "2851.83", "42.24"], False),
                    (["Usuario:CBOSCHI Fecha:11/01/2021 Item:2035"], False),
                ],
            ],
            right_align_cols=(2, 3),
        )
    )
    reader = FileSpreadsheetReader(pdf_reader=PdfPriceListReader(vision_client=None))
    use_case = ImportFirstTime(
        reader,
        InMemoryImportSessionRepository(),
        [ClassifierStage("heuristics", HeuristicColumnClassifier(), 0.75)],
        None,
    )

    session = use_case.start(pdf, "Domitec")

    assert all(n.code != "pdf_vision_extracted" for n in session.notices)
    assert session.source_notices == ()
    assert [c.header for c in session.columns] == ["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"]
    session = use_case.set_roles(
        session.id,
        {
            0: ColumnRole.CODE,
            1: ColumnRole.DESCRIPTION,
            2: ColumnRole.COST_PRICE,
            3: ColumnRole.IGNORE,
        },
    )
    session = use_case.answer(session.id, "price_includes_vat", "no")
    session = use_case.answer(session.id, "currency", "ARS")
    page = use_case.preview(session.id)
    assert page.totals["accepted"] == 4
    accepted = [item for item in page.items if item.record is not None]
    assert [item.record["supplier_code"] for item in accepted] == [
        "055170911",
        "055152911",
        "069151999",
        "068152912",
    ]
    assert str(accepted[0].record["unit_cost_net"]) == "1286.26"


def test_borderless_domitec_import_preserves_optional_unit_price_and_reuses_it(tmp_path):
    from decimal import Decimal
    from pricor.adapters.csv_exporter import CsvExporter
    from pricor.adapters.xlsx_exporter import XlsxExporter
    from pricor.ports.exporter import ImportExport
    from pricor.ports.price_history import ImportedRecord

    pdf = tmp_path / "domitec.pdf"
    pdf.write_bytes(
        borderless_pdf_bytes(
            [
                [
                    (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
                    (["055170911", "DET CONC 2X10 LT LIMPIA MOTOR", "1286.26", "64.31"], False),
                    (["069151999", "SOLO ENVASE SIN FRACCIONAR", "250.80", ""], False),
                ],
                [
                    (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
                    (["068152912", "CERA LIQUIDA 3X4.5 LTS NEGRA", "2851.83", "42.24"], False),
                ],
            ],
            right_align_cols=(2, 3),
        )
    )
    reader = FileSpreadsheetReader(pdf_reader=PdfPriceListReader(vision_client=None))
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
        session = use_case.start(pdf, "Domitec")
        # Heuristics proposes PR. UNIT as unit_price automatically.
        assert session.columns[3].proposals[0].role is ColumnRole.UNIT_PRICE

        session = use_case.set_roles(
            session.id,
            {
                0: ColumnRole.CODE,
                1: ColumnRole.DESCRIPTION,
                2: ColumnRole.COST_PRICE,
                3: ColumnRole.UNIT_PRICE,
            },
        )
        session = use_case.answer(session.id, "price_includes_vat", "no")
        session = use_case.answer(session.id, "currency", "ARS")
        approved = use_case.approve(session.id)
        records = db.history.records_of(approved.id)
        assert [r.record.unit_cost_net for r in records] == [
            Decimal("1286.26"),
            Decimal("250.80"),
            Decimal("2851.83"),
        ]
        assert [r.record.unit_price for r in records] == [
            Decimal("64.31"),
            None,
            Decimal("42.24"),
        ]

        export_data = ImportExport(
            "Domitec",
            tuple(ImportedRecord(r.row_number, r.record) for r in records),
            (),
            ("COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"),
        )
        csv_text = CsvExporter().export(export_data).decode("utf-8-sig")
        assert "unit_price" in csv_text.splitlines()[0]
        assert "64.31" in csv_text
        assert XlsxExporter().export(export_data).startswith(b"PK")

        # Next import reuses the saved unit_price role automatically.
        reused = use_case.start(pdf, "Domitec")
        assert reused.mode == "reuse"
        assert reused.columns[3].role is ColumnRole.UNIT_PRICE
        assert reused.columns[3].decided_by == "saved_plan"
    finally:
        db.close()
