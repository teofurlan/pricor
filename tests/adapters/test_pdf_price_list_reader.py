import pytest

from pricor.adapters.pdf_price_list_reader import PdfPriceListReader
from pricor.ports.chat_client import ChatReply
from pricor.ports.model_errors import ModelTimeoutError, ModelUnavailableError
from pricor.ports.spreadsheet import (
    FileTooLargeError,
    SheetNotFoundError,
    SpreadsheetError,
    TooManyRowsError,
)

from .pdf_fixtures import borderless_pdf_bytes, pdf_bytes


class FakeVisionClient:
    def __init__(self, replies=None, error=None):
        self.replies = list(replies or [])
        self.error = error
        self.calls = []

    def chat_json_with_images(self, system, user, images, schema):
        self.calls.append(
            {"system": system, "user": user, "images": list(images), "schema": schema}
        )
        if self.error is not None:
            raise self.error
        content = self.replies.pop(0)
        return ChatReply(content, 0.1)


def write_pdf(tmp_path, pages, name="lista.pdf"):
    path = tmp_path / name
    path.write_bytes(pdf_bytes(pages))
    return path


def test_sheet_names_validates_fast_without_reading_tables_or_vision(tmp_path):
    path = write_pdf(tmp_path, [["just plain text"]], name="catalogo.pdf")
    vision = FakeVisionClient(error=AssertionError("vision must not be called"))

    names = PdfPriceListReader(vision_client=vision).sheet_names(path)

    assert names == ["catalogo"]
    assert vision.calls == []


def test_sheet_names_rejects_oversized_and_non_pdf_files(tmp_path):
    path = write_pdf(tmp_path, [[["Cod", "Precio"], ["1", "10"]]])
    with pytest.raises(FileTooLargeError):
        PdfPriceListReader(max_file_bytes=10).sheet_names(path)

    bad = tmp_path / "fake.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(SpreadsheetError, match="cannot read the PDF"):
        PdfPriceListReader().sheet_names(bad)


def test_reads_single_page_digital_table_without_vision(tmp_path):
    path = write_pdf(
        tmp_path,
        [[["Codigo", "Descripcion", "Costo"], ["001", "Tornillo", "10,50"], ["002", "Tuerca", "5,00"]]],
    )
    vision = FakeVisionClient(error=AssertionError("vision must not be called"))

    sheet = PdfPriceListReader(vision_client=vision).read_sheet(path)

    assert sheet.name == "lista"
    assert sheet.extraction == "pdf_table"
    assert sheet.rows == (
        ("Codigo", "Descripcion", "Costo"),
        ("001", "Tornillo", "10,50"),
        ("002", "Tuerca", "5,00"),
    )
    assert vision.calls == []


def test_merges_multipage_digital_tables_and_deduplicates_repeated_headers(tmp_path):
    path = write_pdf(
        tmp_path,
        [
            [["Codigo", "Detalle", "Costo"], ["001", "Tornillo", "10,50"]],
            [["Codigo", "Detalle", "Costo"], ["002", "Tuerca", "5,00"]],
            [["codigo", "detalle", "costo"], ["003", "Arandela", "2,00"]],
        ],
    )
    vision = FakeVisionClient(error=AssertionError("vision must not be called"))

    sheet = PdfPriceListReader(vision_client=vision).read_sheet(path)

    assert sheet.extraction == "pdf_table"
    assert sheet.rows == (
        ("Codigo", "Detalle", "Costo"),
        ("001", "Tornillo", "10,50"),
        ("002", "Tuerca", "5,00"),
        ("003", "Arandela", "2,00"),
    )


def test_picks_dominant_column_width_ignoring_small_metadata_box(tmp_path):
    path = write_pdf(
        tmp_path,
        [
            [["Proveedor", "Distribuidora X"]],
            [
                ["Cod", "Desc", "Moneda", "Costo"],
                ["A1", "Item 1", "ARS", "100"],
                ["A2", "Item 2", "ARS", "200"],
                ["A3", "Item 3", "ARS", "300"],
            ],
        ],
    )

    sheet = PdfPriceListReader().read_sheet(path)

    assert sheet.extraction == "pdf_table"
    assert sheet.rows == (
        ("Cod", "Desc", "Moneda", "Costo"),
        ("A1", "Item 1", "ARS", "100"),
        ("A2", "Item 2", "ARS", "200"),
        ("A3", "Item 3", "ARS", "300"),
    )


def test_falls_back_to_vision_for_borderless_or_scanned_pdf_in_batches(tmp_path):
    path = write_pdf(
        tmp_path,
        [
            ["SKU 001  Tornillo  100,00"],
            ["SKU 002  Tuerca    200,00"],
            ["SKU 003  Arandela  300,00"],
        ],
    )
    vision = FakeVisionClient(
        replies=[
            {
                "columns": ["Codigo", "Descripcion", "Precio"],
                "rows": [["001", "Tornillo", "100,00"], ["002", "Tuerca", "200,00"]],
            },
            {
                "columns": ["Codigo", "Descripcion", "Precio"],
                "rows": [["Codigo", "Descripcion", "Precio"], ["003", "Arandela", "300,00"]],
            },
        ]
    )
    rendered_batches = []

    def fake_render(pdf_path, max_pages, dpi):
        rendered_batches.append((pdf_path, max_pages, dpi))
        return [b"png-1", b"png-2", b"png-3"]

    sheet = PdfPriceListReader(
        vision_client=vision,
        vision_batch_pages=2,
        page_renderer=fake_render,
    ).read_sheet(path)

    assert sheet.extraction == "pdf_vision"
    assert len(vision.calls) == 2
    assert len(vision.calls[0]["images"]) == 2
    assert len(vision.calls[1]["images"]) == 1
    assert "Codigo" in vision.calls[1]["user"]
    assert sheet.rows == (
        ("Codigo", "Descripcion", "Precio"),
        ("001", "Tornillo", "100,00"),
        ("002", "Tuerca", "200,00"),
        ("003", "Arandela", "300,00"),
    )


def test_real_pypdfium2_renderer_produces_png_bytes_for_vision(tmp_path):
    path = write_pdf(tmp_path, [["SKU 001  Tornillo  100,00"]])
    vision = FakeVisionClient(
        replies=[
            {
                "columns": ["SKU", "Detalle", "Precio"],
                "rows": [["001", "Tornillo", "100,00"]],
            }
        ]
    )

    sheet = PdfPriceListReader(vision_client=vision).read_sheet(path)

    assert sheet.extraction == "pdf_vision"
    assert len(vision.calls) == 1
    img = vision.calls[0]["images"][0]
    assert img.startswith(b"\x89PNG")


def test_scanned_pdf_without_vision_client_raises_spreadsheet_error(tmp_path):
    path = write_pdf(tmp_path, [["no table here"]])
    with pytest.raises(SpreadsheetError, match="no vision model"):
        PdfPriceListReader(vision_client=None).read_sheet(path)


def test_scanned_pdf_over_max_vision_pages_raises_spreadsheet_error(tmp_path):
    path = write_pdf(tmp_path, [["p1"], ["p2"], ["p3"]])
    vision = FakeVisionClient()
    with pytest.raises(SpreadsheetError, match="3 pages.*2"):
        PdfPriceListReader(vision_client=vision, max_vision_pages=2).read_sheet(path)
    assert vision.calls == []


def test_digital_pdf_over_max_digital_pages_raises_spreadsheet_error(tmp_path):
    path = write_pdf(
        tmp_path,
        [
            [["Cod", "Precio"], ["1", "10"]],
            [["Cod", "Precio"], ["2", "20"]],
            [["Cod", "Precio"], ["3", "30"]],
        ],
    )
    with pytest.raises(SpreadsheetError, match="3 pages.*2"):
        PdfPriceListReader(max_digital_pages=2).read_sheet(path)


@pytest.mark.parametrize(
    ("error", "reply"),
    [
        (ModelUnavailableError("down"), None),
        (ModelTimeoutError("slow"), None),
        (None, {"wrong": "shape"}),
        (None, {"columns": ["A"], "rows": [123]}),
    ],
)
def test_vision_failures_and_bad_schemas_surface_as_spreadsheet_error(tmp_path, error, reply):
    path = write_pdf(tmp_path, [["no table here"]])
    vision = FakeVisionClient(replies=[reply] if reply is not None else [], error=error)
    with pytest.raises(SpreadsheetError, match="visual reader"):
        PdfPriceListReader(vision_client=vision, page_renderer=lambda *_: [b"png"]).read_sheet(path)


def test_enforces_max_rows_and_wrong_sheet_name_and_corrupt_pdf(tmp_path):
    path = write_pdf(
        tmp_path,
        [[["Cod", "Precio"], ["1", "10"], ["2", "20"], ["3", "30"]]],
    )
    with pytest.raises(TooManyRowsError):
        PdfPriceListReader(max_rows=2).read_sheet(path)
    with pytest.raises(SheetNotFoundError):
        PdfPriceListReader().read_sheet(path, sheet="otra")

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken")
    with pytest.raises(SpreadsheetError, match="cannot read the PDF"):
        PdfPriceListReader().read_sheet(bad)


def test_reads_multipage_borderless_presea_style_pdf_without_vision(tmp_path):
    pages = [
        [
            (["LISTA DE PRECIOS VENTA SUELTOS"], False),
            (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
            (["GRUPO DE PRODUCTOS 01 - AUTOMOVIL"], False),
            (["055170911", "DET CONC 2X10 LT LIMPIA MOTOR", "1286.26", "64.31"], False),
            (["069151911", "REVIVIDOR SILICONADO 1X4.5 LT MULTIUSO", "2188.67", "486.37"], False),
            (["069151999", "SOLO ENVASE SIN FRACCIONAR", "250.80", ""], False),
            (["Usuario:CBOSCHI Fecha:11/01/2021 Item:2035 Reporte:_LISTA PRECIOS"], False),
        ],
        [
            (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
            (["068152912", "CERA LIQUIDA 3X4.5 LTS NEGRA (1+4)", "2851.83", "42.24"], False),
            (["112151962", "DESENGRASANTE 1X4.5 LT PARA MANOS", "1018.94", "226.43"], False),
            (["Usuario:CBOSCHI Fecha:11/01/2021 Item:2035 Reporte:_LISTA PRECIOS"], False),
        ],
    ]
    path = tmp_path / "domitec.pdf"
    path.write_bytes(borderless_pdf_bytes(pages, right_align_cols=(2, 3)))
    vision = FakeVisionClient(error=AssertionError("vision must not be called"))

    sheet = PdfPriceListReader(vision_client=vision).read_sheet(path)

    assert sheet.extraction == "pdf_table"
    assert vision.calls == []
    assert sheet.rows[0] == ("COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT")
    assert ("055170911", "DET CONC 2X10 LT LIMPIA MOTOR", "1286.26", "64.31") in sheet.rows
    assert ("069151999", "SOLO ENVASE SIN FRACCIONAR", "250.80", None) in sheet.rows
    assert ("068152912", "CERA LIQUIDA 3X4.5 LTS NEGRA (1+4)", "2851.83", "42.24") in sheet.rows
    assert ("112151962", "DESENGRASANTE 1X4.5 LT PARA MANOS", "1018.94", "226.43") in sheet.rows
    # Repeated header on page 2 and repeated footer on both pages are stripped.
    assert sum(1 for row in sheet.rows if row[0] == "COD_ALFA") == 1
    assert all("Usuario:CBOSCHI" not in (cell or "") for row in sheet.rows for cell in row)


def test_reads_single_page_completely_unruled_borderless_pdf(tmp_path):
    pages = [
        [
            (["Codigo", "Descripcion", "Precio"], False),
            (["001", "Tornillo 8x1", "100,50"], False),
            (["002", "Tuerca M8", "50,00"], False),
        ]
    ]
    path = tmp_path / "unruled.pdf"
    path.write_bytes(
        borderless_pdf_bytes(pages, col_x=(40, 120, 420), right_align_cols=(2,))
    )
    vision = FakeVisionClient(error=AssertionError("vision must not be called"))

    sheet = PdfPriceListReader(vision_client=vision).read_sheet(path)

    assert sheet.extraction == "pdf_table"
    assert vision.calls == []
    assert sheet.rows == (
        ("Codigo", "Descripcion", "Precio"),
        ("001", "Tornillo 8x1", "100,50"),
        ("002", "Tuerca M8", "50,00"),
    )


def test_borderless_pdf_keeps_long_description_separate_from_price_and_enforces_max_rows(tmp_path):
    pages = [
        [
            (["COD", "DETALLE", "PRECIO"], False),
            (["A1", "DET CONC 3X4.5 LT LIMPIACARROCERIA SILICON PREMIUM EXTRA CONCENTRADO", "2196.39"], False),
            (["A2", "LIMPIADOR LIQUIDO MULTIUSO CONCENTRADO", "855.00"], False),
            (["A3", "CLAVO ACERO", "60.50"], False),
        ]
    ]
    path = tmp_path / "wide_desc.pdf"
    path.write_bytes(
        borderless_pdf_bytes(pages, col_x=(40, 100, 460), right_align_cols=(2,))
    )

    sheet = PdfPriceListReader().read_sheet(path)
    assert sheet.extraction == "pdf_table"
    assert sheet.rows[1] == (
        "A1",
        "DET CONC 3X4.5 LT LIMPIACARROCERIA SILICON PREMIUM EXTRA CONCENTRADO",
        "2196.39",
    )

    with pytest.raises(TooManyRowsError):
        PdfPriceListReader(max_rows=2).read_sheet(path)


def test_borderless_pdf_keeps_code_and_description_separate_despite_frequent_section_rows(tmp_path):
    # Reproduces the Domitec/Presea failure mode: ~10% 2-segment "GRUPO DE PRODUCTOS" rows
    # span the narrow gutter between COD_ALFA and DETALLE, exceeding the 5% floor.
    section_line = (["GRUPO DE PRODUCTOS    01 - AUTOMOVIL"], False)
    product_rows = [
        ([f"0551709{i:02d}", f"DET CONC 2X10 LT LIMPIA MOTOR {i}", f"{1000 + i}.26", "64.31"], False)
        for i in range(18)
    ]
    pages = [
        [
            (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
            section_line,
            *product_rows[:9],
            section_line,
            (["Usuario:CBOSCHI Fecha:11/01/2021 Item:2035"], False),
        ],
        [
            (["COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT"], True),
            section_line,
            *product_rows[9:],
            (["Usuario:CBOSCHI Fecha:11/01/2021 Item:2035"], False),
        ],
    ]
    path = tmp_path / "domitec_sections.pdf"
    path.write_bytes(
        borderless_pdf_bytes(pages, col_x=(40, 100, 410, 500), right_align_cols=(2, 3))
    )

    sheet = PdfPriceListReader().read_sheet(path)

    assert sheet.extraction == "pdf_table"
    assert sheet.rows[0] == ("COD_ALFA", "DETALLE", "PRECIO", "PR. UNIT")
    assert ("055170900", "DET CONC 2X10 LT LIMPIA MOTOR 0", "1000.26", "64.31") in sheet.rows


def test_borderless_two_column_pdf_splits_past_section_gutter(tmp_path):
    # Even when section rows also have 2 segments (same mode as the table), relative valley
    # splitting keeps the two columns separated.
    section = (["GRUPO    RUBRO"], False)
    rows = [([f"DETALLE PRODUCTO {i}", f"{200 + i}.50"], False) for i in range(18)]
    path = tmp_path / "two_cols.pdf"
    path.write_bytes(
        borderless_pdf_bytes(
            [[(["DETALLE", "PRECIO"], False), section, *rows, section]],
            col_x=(40, 320),
            right_align_cols=(1,),
        )
    )

    sheet = PdfPriceListReader().read_sheet(path)

    assert sheet.extraction == "pdf_table"
    assert sheet.rows[0] == ("DETALLE", "PRECIO")
    assert ("DETALLE PRODUCTO 0", "200.50") in sheet.rows
