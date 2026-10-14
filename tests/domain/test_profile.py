from datetime import datetime
from decimal import Decimal

import pytest

from pricor.domain.profile import (
    ColumnType,
    RowClass,
    engine_input,
    profile_sheet,
)

HEADER = ("Código", "Descripción", "Precio", "IVA", "EAN", "Fecha")


def _data(i: int) -> tuple:
    return (f"A-{i:03d}", f"Producto {i}", f"{1000 + i},50", "21%", f"779123456{i:04d}", None)


def _sheet() -> list[tuple]:
    return [
        ("LISTA DE PRECIOS OCTUBRE", None, None, None, None, None),
        (None, None, None, None, None, None),
        ("Distribuidora Ejemplo SA", "Tel 4444-5555", None, None, None, None),
        HEADER,
        ("FERRETERIA", None, None, None, None, None),
        _data(1),
        _data(2),
        (None, None, None, None, None, None),
        ("BULONERIA", None, None, None, None, None),
        _data(3),
        ("Subtotal", None, "3.100,00", None, None, None),
        ("TOTAL GENERAL", None, "9.999,00", None, None, None),
    ]


# -- header detection --


def test_header_found_after_title_rows():
    profile = profile_sheet(_sheet())
    assert profile.header_row == 3
    assert not profile.header_ambiguous
    assert profile.header_confidence >= 0.7


def test_header_in_first_row():
    profile = profile_sheet([HEADER, _data(1), _data(2)])
    assert profile.header_row == 0


def test_header_only_searched_in_first_30_rows():
    rows = [("banner",)] * 40 + [HEADER, _data(1)]
    assert profile_sheet(rows).header_row is None


def test_no_header_in_numeric_sheet_is_reported_not_guessed():
    profile = profile_sheet([(1, 2, 3), (4, 5, 6)])
    assert profile.header_row is None
    assert profile.header_ambiguous


def test_stacked_header_like_rows_are_ambiguous():
    rows = [("Código", "Descripción", "Precio"), ("Ref", "Detalle", "Importe"), ("A1", "x", "1,5")]
    profile = profile_sheet(rows)
    assert profile.header_ambiguous


def test_duplicate_headers_are_flagged():
    rows = [("Código", "Precio", " precio "), ("A1", "1,5", "2,5")]
    profile = profile_sheet(rows)
    assert profile.duplicated_headers == ("precio",)


def test_no_duplicates_reported_when_headers_are_distinct():
    assert profile_sheet(_sheet()).duplicated_headers == ()


# -- row classification --


def test_every_row_gets_exactly_one_class_and_counts_add_up():
    rows = _sheet()
    profile = profile_sheet(rows)
    indexes = [item.index for item in profile.row_classes]
    assert indexes == [i for i in range(len(rows)) if i != profile.header_row]
    counts = profile.class_counts
    assert sum(counts.values()) == len(rows) - 1
    assert counts[RowClass.PREAMBLE] == 2
    assert counts[RowClass.SECTION] == 2
    assert counts[RowClass.EMPTY] == 2
    assert counts[RowClass.TOTAL] == 2
    assert counts[RowClass.DATA] == 3


def test_classes_by_index():
    profile = profile_sheet(_sheet())
    by_index = {item.index: item.kind for item in profile.row_classes}
    assert by_index[0] is RowClass.PREAMBLE
    assert by_index[4] is RowClass.SECTION
    assert by_index[5] is RowClass.DATA
    assert by_index[7] is RowClass.EMPTY
    assert by_index[10] is RowClass.TOTAL
    assert by_index[11] is RowClass.TOTAL


@pytest.mark.parametrize("label", ["TOTAL", "total", "Totales", "SUBTOTAL", "Sub-total", "Total general"])
def test_total_labels(label):
    rows = [("Código", "Precio"), ("A1", "1,5"), (label, "9,5")]
    by_index = {item.index: item.kind for item in profile_sheet(rows).row_classes}
    assert by_index[2] is RowClass.TOTAL


def test_product_starting_with_total_text_is_still_data():
    rows = [("Código", "Descripción"), ("A1", "Total black pintura")]
    by_index = {item.index: item.kind for item in profile_sheet(rows).row_classes}
    assert by_index[1] is RowClass.DATA


def test_whitespace_only_row_is_empty():
    rows = [("Código", "Precio"), ("A1", "1,5"), ("  ", " ")]
    by_index = {item.index: item.kind for item in profile_sheet(rows).row_classes}
    assert by_index[2] is RowClass.EMPTY


def test_single_column_table_has_no_section_rows():
    rows = [("Código",), ("A1",), ("A2",)]
    counts = profile_sheet(rows).class_counts
    assert counts[RowClass.DATA] == 2
    assert counts[RowClass.SECTION] == 0


# -- columns --


def test_column_basics_exclude_non_data_rows():
    profile = profile_sheet(_sheet())
    column = profile.columns[0]
    assert column.raw_header == "Código"
    assert column.header == "código"
    assert column.apparent_type is ColumnType.CODE
    assert column.null_ratio == 0.0
    assert column.distinct_ratio == 1.0


def test_normalized_header_collapses_whitespace_and_case():
    profile = profile_sheet([("  Precio   Lista ", "x"), ("1,5", "y")])
    assert profile.columns[0].header == "precio lista"
    assert profile.columns[0].raw_header == "  Precio   Lista "


def test_empty_column():
    rows = [("Código", "Notas"), ("A1", None), ("A2", None)]
    column = profile_sheet(rows).columns[1]
    assert column.apparent_type is ColumnType.EMPTY
    assert column.null_ratio == 1.0
    assert column.number_format is None


def test_null_and_distinct_ratio():
    rows = [("Código", "Marca"), ("A1", "X"), ("A2", "X"), ("A3", None), ("A4", "Y")]
    column = profile_sheet(rows).columns[1]
    assert column.null_ratio == 0.25
    assert column.distinct_ratio == pytest.approx(2 / 3)


def test_barcode_column():
    profile = profile_sheet(_sheet())
    assert profile.columns[4].apparent_type is ColumnType.BARCODE


@pytest.mark.parametrize("digits", [8, 12, 13, 14])
def test_barcode_lengths(digits):
    rows = [("Código", "EAN"), ("A1", "1" * digits), ("A2", "2" * digits)]
    assert profile_sheet(rows).columns[1].apparent_type is ColumnType.BARCODE


def test_native_integer_barcodes():
    rows = [("Código", "EAN"), ("A1", 7791234567890), ("A2", 7791234567891)]
    assert profile_sheet(rows).columns[1].apparent_type is ColumnType.BARCODE


def test_percent_column():
    profile = profile_sheet(_sheet())
    assert profile.columns[3].apparent_type is ColumnType.PERCENT


def test_integer_and_decimal_columns():
    rows = [("A", "B"), ("1", "1,5"), ("2", "2,25"), ("3", "10,0")]
    profile = profile_sheet(rows)
    assert profile.columns[0].apparent_type is ColumnType.INTEGER
    assert profile.columns[1].apparent_type is ColumnType.DECIMAL


def test_native_decimal_cells():
    rows = [("A", "B"), (Decimal("1.5"), 3), (Decimal("2.25"), 4)]
    profile = profile_sheet(rows)
    assert profile.columns[0].apparent_type is ColumnType.DECIMAL
    assert profile.columns[1].apparent_type is ColumnType.INTEGER


def test_date_column_native_and_text():
    rows = [("A", "B"), (datetime(2026, 1, 1), "01/02/2026"), (datetime(2026, 1, 2), "2026-03-04")]
    profile = profile_sheet(rows)
    assert profile.columns[0].apparent_type is ColumnType.DATE
    assert profile.columns[1].apparent_type is ColumnType.DATE


def test_text_column():
    profile = profile_sheet(_sheet())
    assert profile.columns[1].apparent_type is ColumnType.TEXT


def test_money_column_and_currency_markers():
    rows = [("Item", "Precio"), ("a", "$ 1.200,50"), ("b", "$ 850,5"), ("c", "U$S 10,00")]
    column = profile_sheet(rows).columns[1]
    assert column.apparent_type is ColumnType.MONEY
    assert set(column.currencies) == {"$", "U$S"}


@pytest.mark.parametrize(
    ("text", "marker"),
    [("USD 10,5", "USD"), ("ARS 10,5", "ARS"), ("10,5 USD", "USD"), ("u$s 10,5", "U$S")],
)
def test_currency_marker_variants(text, marker):
    rows = [("Item", "Precio"), ("a", text), ("b", text)]
    assert profile_sheet(rows).columns[1].currencies == (marker,)


def test_currency_in_header_is_reported_separately():
    rows = [("Item", "Precio USD"), ("a", "10,5"), ("b", "11,5")]
    column = profile_sheet(rows).columns[1]
    assert column.header_currencies == ("USD",)
    assert column.currencies == ()


def test_dotted_reference_numbers_are_codes_not_decimals():
    rows = [("Item", "Ref"), ("a", "1.5.12"), ("b", "76.10.22")]
    column = profile_sheet(rows).columns[1]
    assert column.apparent_type is ColumnType.CODE
    assert column.number_format is None


# -- number format --


def test_argentine_format_column():
    rows = [("Item", "Precio"), ("a", "12.100,00"), ("b", "850,5"), ("c", "1.234,56")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert (fmt.decimal_sep, fmt.thousands_sep) == (",", ".")
    assert not fmt.ambiguous
    assert "," in fmt.evidence


def test_us_format_column():
    rows = [("Item", "Precio"), ("a", "12,100.00"), ("b", "850.5")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert (fmt.decimal_sep, fmt.thousands_sep) == (".", ",")
    assert not fmt.ambiguous


def test_column_of_1_234_values_is_ambiguous():
    rows = [("Item", "Precio"), ("a", "1.234"), ("b", "5.678"), ("c", "2.500")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert fmt.ambiguous
    assert fmt.decimal_sep is None and fmt.thousands_sep is None
    assert fmt.evidence


def test_one_unambiguous_value_resolves_the_rest():
    rows = [("Item", "Precio"), ("a", "1.234"), ("b", "850,5")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert (fmt.decimal_sep, fmt.thousands_sep) == (",", ".")
    assert not fmt.ambiguous


def test_conflicting_evidence_is_ambiguous():
    rows = [("Item", "Precio"), ("a", "850,5"), ("b", "10.25")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert fmt.ambiguous


def test_multiple_group_separators_prove_thousands():
    rows = [("Item", "Precio"), ("a", "1.234.567"), ("b", "2.000")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert (fmt.decimal_sep, fmt.thousands_sep) == (",", ".")
    assert not fmt.ambiguous


def test_leading_zero_proves_decimal_point():
    rows = [("Item", "Precio"), ("a", "0.125"), ("b", "0.250")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert fmt.decimal_sep == "."
    assert not fmt.ambiguous


def test_native_numbers_need_no_separator():
    rows = [("Item", "Precio"), ("a", Decimal("1.234")), ("b", 5)]
    fmt = profile_sheet(rows).columns[1].number_format
    assert fmt.decimal_sep is None and fmt.thousands_sep is None
    assert not fmt.ambiguous
    assert "native" in fmt.evidence


def test_plain_integers_have_no_separator_and_are_not_ambiguous():
    rows = [("Item", "Cant"), ("a", "10"), ("b", "250")]
    fmt = profile_sheet(rows).columns[1].number_format
    assert not fmt.ambiguous
    assert fmt.decimal_sep is None


def test_text_columns_have_no_number_format():
    assert profile_sheet(_sheet()).columns[1].number_format is None


# -- samples --


def test_samples_include_representative_and_atypical_values():
    rows = [("Item", "Precio")]
    rows += [(f"a{i}", f"{i},50") for i in range(1, 11)]
    rows += [("zz", "consultar")]
    column = profile_sheet(rows).columns[1]
    assert 1 <= len(column.samples) <= 5
    kinds = {sample.kind: sample.value for sample in column.atypical}
    assert kinds["off_type"] == "consultar"
    assert kinds["max"] == "10,50"
    assert kinds["min"] == "1,50"
    assert "longest" in kinds


def test_atypical_samples_carry_row_index():
    rows = [("Item", "Precio")] + [(f"a{i}", f"{i},5") for i in range(5)] + [("c", "n/a")]
    off = [s for s in profile_sheet(rows).columns[1].atypical if s.kind == "off_type"]
    assert [s.row_index for s in off] == [6]


def test_min_max_skipped_when_format_is_ambiguous():
    rows = [("Item", "Precio"), ("a", "1.234"), ("b", "5.678")]
    kinds = {s.kind for s in profile_sheet(rows).columns[1].atypical}
    assert "min" not in kinds and "max" not in kinds


# -- engine compatibility --


def test_engine_input_preserves_file_row_numbers():
    rows = _sheet()
    profile = profile_sheet(rows)
    headers, data = engine_input(rows, profile)
    assert headers == list(HEADER)
    assert [number for number, _ in data] == [6, 7, 10]  # 1-based file rows
    assert data[0][1] == rows[5]


def test_engine_input_requires_a_header():
    rows = [(1, 2), (3, 4)]
    with pytest.raises(ValueError, match="header"):
        engine_input(rows, profile_sheet(rows))


def test_engine_input_feeds_the_engine_with_original_row_numbers():
    from pricor.domain.engine import execute_numbered_rows
    from pricor.domain.plan import parse_plan

    from .golden import GOLDEN_HEADERS, golden_plan_dict

    golden_row = ("00123 ", "  TORNILLO AUTOP.   8x1  ", "$ 12.100,00", "10", "10+5", "21%")
    rows = [
        ("LISTA", None, None, None, None, None),
        tuple(GOLDEN_HEADERS),
        golden_row,
        ("TOTAL", None, "1,00", None, None, None),
    ]
    headers, data = engine_input(rows, profile_sheet(rows))
    plan = parse_plan(golden_plan_dict())
    accepted = execute_numbered_rows(plan, headers, data).accepted
    assert [row.row_number for row in accepted] == [3]
    assert accepted[0].record.unit_cost_net == Decimal("855.00")


def test_lone_code_like_cell_is_a_sparse_data_row_not_a_section():
    rows = [("Código", "Marca"), ("A1", "X"), ("A3", None)]
    by_index = {item.index: item.kind for item in profile_sheet(rows).row_classes}
    assert by_index[2] is RowClass.DATA


# -- user-chosen header row --


def test_forced_header_row_overrides_detection():
    rows = _sheet()
    profile = profile_sheet(rows, header_row=0)
    assert profile.header_row == 0
    assert profile.header_confidence == 1.0
    assert profile.header_ambiguous is False


def test_forced_header_row_none_means_header_less():
    rows = [("A-001", "Producto 1", "10,50"), ("A-002", "Producto 2", "11,50")]
    profile = profile_sheet(rows, header_row=None)
    assert profile.header_row is None
    assert [c.plan_header for c in profile.columns] == ["column_0", "column_1", "column_2"]
    assert profile.class_counts[RowClass.DATA] == 2


def test_forced_header_row_out_of_range_is_rejected():
    with pytest.raises(ValueError, match="header row"):
        profile_sheet(_sheet(), header_row=99)


# -- zero-padded rows --

ZERO_HEADER = ("CODIGO", "COD_PROV", "DESCRIP", "MONEDA", "PRECIO", "DTO", "CAMBIO")


def _zero_sheet(*extra: tuple) -> list[tuple]:
    data = [(i, f"P{i}", f"ARTICULO {i}", "$", Decimal(100 + i), None, None) for i in range(1, 4)]
    return [ZERO_HEADER, *extra, *data]


def _kinds(profile) -> dict[int, RowClass]:
    return {item.index: item.kind for item in profile.row_classes}


def test_row_whose_only_content_is_numeric_zeros_is_empty():
    profile = profile_sheet(_zero_sheet((None, None, None, None, 0, None, None)))

    assert _kinds(profile)[1] is RowClass.EMPTY


def test_row_with_one_text_cell_and_zeros_is_a_section():
    banner = (None, None, "*** ANTENAS TV. COLOR ***", None, 0, None, None)

    profile = profile_sheet(_zero_sheet(banner))

    assert _kinds(profile)[1] is RowClass.SECTION


def test_zero_price_with_real_content_stays_data():
    sparse = ("X1", None, "ARTICULO SIN PRECIO", "$", 0, None, None)

    profile = profile_sheet(_zero_sheet(sparse))

    assert _kinds(profile)[1] is RowClass.DATA


def test_zero_padded_text_row_still_matches_a_total_label():
    profile = profile_sheet(_zero_sheet((None, None, "TOTAL GENERAL", None, 0, None, None)))

    assert _kinds(profile)[1] is RowClass.TOTAL


def test_zero_only_row_above_the_header_is_empty_not_preamble():
    rows = [(None, None, None, None, 0, None, None), *_zero_sheet()]

    profile = profile_sheet(rows)

    assert profile.header_row == 1
    assert _kinds(profile)[0] is RowClass.EMPTY


# -- numeric-majority tolerance --


def _single_column(values: list) -> list[tuple]:
    return [("Codigo", "Valor"), *[(f"A{i}", value) for i, value in enumerate(values)]]


def test_mostly_numeric_column_is_numeric_and_lists_its_outliers():
    values = ["12.100,00"] * 9 + ["consultar"]

    column = profile_sheet(_single_column(values)).columns[1]

    assert column.apparent_type is ColumnType.DECIMAL
    assert [s.value for s in column.atypical if s.kind == "off_type"] == ["consultar"]


def test_numbers_mixed_with_percent_cells_count_as_numeric_like():
    values = ["21", "21", "10,5%", "21", "21", "21%", "21", "21", "21", "21"]

    column = profile_sheet(_single_column(values)).columns[1]

    assert column.apparent_type in (ColumnType.INTEGER, ColumnType.DECIMAL)
    assert [s.value for s in column.atypical if s.kind == "off_type"] == ["10,5%", "21%"]


def test_minority_numbers_do_not_make_a_text_column_numeric():
    values = ["12,50", "tornillo", "tuerca", "arandela", "clavo"]

    column = profile_sheet(_single_column(values)).columns[1]

    assert column.apparent_type is ColumnType.TEXT


# -- distinct values --


def test_a_low_cardinality_column_lists_every_distinct_value_beyond_the_samples():
    values = ["$", "u$s", "usd", "ars", "eur", "pesos", "dolares"]
    rows = [("Item", "Moneda")] + [(f"a{i}", values[i % len(values)]) for i in range(30)]
    column = profile_sheet(rows).columns[1]
    assert len(column.samples) <= 5
    assert set(column.distinct_values) == set(values)


def test_distinct_values_are_normalized_and_deduplicated():
    rows = [("Item", "Moneda"), ("a", "  u$s"), ("b", "u$s "), ("c", "$")]
    column = profile_sheet(rows).columns[1]
    assert sorted(column.distinct_values) == ["$", "u$s"]


def test_a_high_cardinality_column_does_not_list_its_values():
    rows = [("Item", "Descripcion")] + [(f"a{i}", f"Producto {i}") for i in range(200)]
    assert profile_sheet(rows).columns[1].distinct_values is None
