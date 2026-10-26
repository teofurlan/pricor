import io
import re
import zipfile
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.domain.parsing import is_quantity_discount
from pricor.domain.profile import RowClass, profile_sheet
from pricor.samples import SAMPLES, SAMPLES_DIR
from tools.samples.generate import render_week, write_all

HEADER_ROW = 5  # one-based: title, subtitle, two blank rows, then the header


def rows_of(week):
    sheet = load_workbook(io.BytesIO(render_week(week)), data_only=True).active
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def table(week):
    rows = rows_of(week)
    header = [str(cell) for cell in rows[HEADER_ROW - 1]]
    return rows, header, rows[HEADER_ROW:]


def products(week):
    """Data rows that are products (a section row only has its first cell)."""
    rows, header, data = table(week)
    sections = [row for row in data if row[0] and all(cell is None for cell in row[1:])]
    items = [
        dict(zip(header, row, strict=True))
        for row in data
        if any(cell is not None for cell in row) and row not in sections
    ]
    return items, sections


def test_generation_is_deterministic():
    assert render_week(1) == render_week(1)
    assert render_week(2) == render_week(2)


def test_workbook_metadata_carries_no_clock_time():
    # openpyxl stamps `modified` with the current time on save; the files must not depend on it.
    with zipfile.ZipFile(io.BytesIO(render_week(1))) as archive:
        core = archive.read("docProps/core.xml").decode()
        stamps = {info.date_time for info in archive.infolist()}

    assert core.count("2026-01-01T00:00:00Z") == 2
    assert stamps == {(2026, 1, 1, 0, 0, 0)}


def test_write_all_writes_the_catalog_files_and_repeats_byte_for_byte(tmp_path):
    first = {path.name: path.read_bytes() for path in write_all(tmp_path)}
    second = {path.name: path.read_bytes() for path in write_all(tmp_path)}

    assert set(first) == {sample.file_name for sample in SAMPLES}
    assert first == second


def test_shipped_files_match_the_generator():
    for sample in SAMPLES:
        assert (SAMPLES_DIR / sample.file_name).read_bytes() == render_week(sample.week)


def test_week_one_has_a_title_block_above_the_header():
    rows = rows_of(1)

    assert "DISTRIBUIDORA EJEMPLO" in rows[0][0]
    assert all(cell is None for cell in rows[2]) and all(cell is None for cell in rows[3])
    assert [str(cell) for cell in rows[HEADER_ROW - 1] if cell][:3] == ["CODIGO", "COD_PROV", "DESCRIPCION"]


def test_week_one_has_about_three_hundred_products_in_sections():
    items, sections = products(1)

    assert 280 <= len(items) <= 320
    assert len(sections) >= 6
    assert all(re.fullmatch(r"\*\*\* [A-ZÁÉÍÓÚÑ ]+ \*\*\*", row[0]) for row in sections)


def test_internal_code_is_empty_for_part_of_the_products_but_supplier_code_never():
    items, _ = products(1)
    empty = [item for item in items if not item["CODIGO"]]

    assert 0.2 * len(items) < len(empty) < 0.6 * len(items)
    assert all(item["COD_PROV"] for item in items)
    assert len({item["COD_PROV"] for item in items}) == len(items)


def test_prices_are_positive_numbers_without_vat_and_currency_is_mixed():
    items, _ = products(1)

    assert all(isinstance(item["PRECIO SIN IVA"], int | float) and item["PRECIO SIN IVA"] > 0 for item in items)
    assert {item["MONEDA"] for item in items} == {"$", "u$s"}


def test_both_kinds_of_discount_appear_in_their_own_columns():
    items, _ = products(1)
    ordinary = [item["DTO."] for item in items if item["DTO."]]
    conditional = [item["DTO X CANT"] for item in items if item["DTO X CANT"]]

    assert len(ordinary) >= 20 and all(re.fullmatch(r"\d+%", value) for value in ordinary)
    assert len(conditional) >= 20 and all(is_quantity_discount(value) for value in conditional)


def test_the_app_detects_the_features_the_sample_is_meant_to_exercise(tmp_path):
    (path,) = [p for p in write_all(tmp_path) if "semana-1" in p.name]
    profile = profile_sheet(FileSpreadsheetReader().read_sheet(path).rows)
    columns = {column.raw_header: column for column in profile.columns}

    assert profile.header_row == HEADER_ROW - 1
    assert columns["DTO X CANT"].quantity_discount and not columns["DTO."].quantity_discount
    assert columns["CODIGO"].empty_rows > 0 and columns["COD_PROV"].empty_rows == 0


def test_week_two_is_marked_as_simulated_in_name_and_title():
    week_two = next(sample for sample in SAMPLES if sample.week == 2)

    assert "simulada" in week_two.file_name
    assert "SIMULADA" in rows_of(2)[0][0]
    assert "SIMULADA" not in rows_of(1)[0][0]


def test_week_two_adds_drops_changes_prices_and_plants_one_anomaly():
    one = {item["COD_PROV"]: item for item in products(1)[0]}
    two = {item["COD_PROV"]: item for item in products(2)[0]}

    assert 2 <= len(set(two) - set(one)) <= 8
    assert 2 <= len(set(one) - set(two)) <= 8
    ratios = {
        code: Decimal(str(two[code]["PRECIO SIN IVA"])) / Decimal(str(one[code]["PRECIO SIN IVA"]))
        for code in set(one) & set(two)
    }
    tripled = [code for code, ratio in ratios.items() if ratio >= Decimal("2.9")]
    assert len(tripled) == 1
    others = [ratio for code, ratio in ratios.items() if code not in tripled]
    assert all(Decimal("0.85") < ratio < Decimal("1.2") for ratio in others)
    assert any(ratio > 1 for ratio in others) and any(ratio < 1 for ratio in others)
    assert any(ratio == 1 for ratio in others)


def test_week_two_swaps_two_columns_but_keeps_the_same_ones():
    _, header_one, _ = table(1)
    _, header_two, _ = table(2)

    assert sorted(header_one) == sorted(header_two)
    moved = [name for name, other in zip(header_one, header_two, strict=True) if name != other]
    assert len(moved) == 2


@pytest.mark.parametrize("week", [1, 2])
def test_every_product_row_reads_as_data_for_the_app(week, tmp_path):
    path = next(p for p in write_all(tmp_path) if f"semana-{week}" in p.name)
    profile = profile_sheet(FileSpreadsheetReader().read_sheet(path).rows)

    assert profile.header_row == HEADER_ROW - 1
    counts = profile.class_counts
    assert counts[RowClass.SECTION] == 8
    assert counts[RowClass.PREAMBLE] == 2
    assert counts[RowClass.DATA] == len(products(week)[0])
