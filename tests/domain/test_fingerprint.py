import pytest

from pricor.domain.fingerprint import (
    ColumnFingerprint,
    SheetFingerprint,
    compare_fingerprint,
    fingerprint_of,
    types_compatible,
)
from pricor.domain.plan_builder import ConstantSource, PlanParameters, RoleAssignment, build_plan
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole as R

BASE = [
    ["Codigo", "Descripcion", "Precio lista", "IVA"],
    ["A1", "Tornillo", "1.210,00", "21%"],
    ["A2", "Tuerca", "968,00", "21%"],
    ["A3", "Arandela", "121,00", "21%"],
    ["A4", "Clavo", "60,50", "21%"],
]


def saved_of(rows, sheet="Hoja1"):
    return fingerprint_of(profile_sheet(rows), sheet)


def columns(items):
    return [(item.saved_index, item.new_index, item.header) for item in items]


def test_fingerprint_of_records_position_normalized_header_and_type():
    fingerprint = saved_of(BASE, sheet="Lista")

    assert fingerprint.sheet_name == "Lista"
    assert fingerprint.header_row == 0
    assert [(c.index, c.header, c.apparent_type) for c in fingerprint.columns] == [
        (0, "codigo", "code"),
        (1, "descripcion", "text"),
        (2, "precio lista", "decimal"),
        (3, "iva", "percent"),
    ]


def test_an_identical_sheet_has_no_changes():
    result = compare_fingerprint(saved_of(BASE), profile_sheet(BASE), "Hoja1")

    assert columns(result.unchanged) == [
        (0, 0, "codigo"),
        (1, 1, "descripcion"),
        (2, 2, "precio lista"),
        (3, 3, "iva"),
    ]
    assert not result.has_changes
    assert result.moved == result.retyped == result.new == result.missing == ()
    assert result.sheet_change is None
    assert result.header_row_change is None


def test_header_case_and_spacing_do_not_count_as_a_change():
    rows = [["  CODIGO ", "descripcion", "PRECIO   LISTA", "iva"], *BASE[1:]]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert not result.has_changes


def test_a_column_at_a_new_position_is_reported_as_moved():
    rows = [
        ["Descripcion", "Codigo", "Precio lista", "IVA"],
        ["Tornillo", "A1", "1.210,00", "21%"],
        ["Tuerca", "A2", "968,00", "21%"],
        ["Arandela", "A3", "121,00", "21%"],
        ["Clavo", "A4", "60,50", "21%"],
    ]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert columns(result.moved) == [(0, 1, "codigo"), (1, 0, "descripcion")]
    assert columns(result.unchanged) == [(2, 2, "precio lista"), (3, 3, "iva")]
    assert result.new == result.missing == result.retyped == ()
    assert result.has_changes


def test_an_inserted_column_moves_the_ones_after_it_and_is_itself_new():
    rows = [
        ["Extra", "Codigo", "Descripcion", "Precio lista", "IVA"],
        ["x", "A1", "Tornillo", "1.210,00", "21%"],
        ["y", "A2", "Tuerca", "968,00", "21%"],
        ["z", "A3", "Arandela", "121,00", "21%"],
        ["w", "A4", "Clavo", "60,50", "21%"],
    ]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert [(c.saved_index, c.new_index) for c in result.moved] == [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert [c.new_index for c in result.new] == [0]
    assert result.new[0].header == "extra"


def test_a_header_whose_values_changed_type_is_retyped():
    rows = [
        ["Codigo", "Descripcion", "Precio lista", "IVA"],
        ["A1", "Tornillo", "consultar", "21%"],
        ["A2", "Tuerca", "a pedido", "21%"],
        ["A3", "Arandela", "consultar", "21%"],
        ["A4", "Clavo", "a pedido", "21%"],
    ]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert [(c.saved_index, c.new_index, c.saved_type, c.new_type) for c in result.retyped] == [
        (2, 2, "decimal", "text")
    ]
    assert columns(result.unchanged) == [(0, 0, "codigo"), (1, 1, "descripcion"), (3, 3, "iva")]


def test_a_retyped_column_that_also_moved_is_retyped_not_moved():
    rows = [
        ["Codigo", "Descripcion", "IVA", "Precio lista"],
        ["A1", "Tornillo", "21%", "consultar"],
        ["A2", "Tuerca", "21%", "a pedido"],
        ["A3", "Arandela", "21%", "consultar"],
        ["A4", "Clavo", "21%", "a pedido"],
    ]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert [(c.saved_index, c.new_index) for c in result.retyped] == [(2, 3)]
    assert [(c.saved_index, c.new_index) for c in result.moved] == [(3, 2)]


def test_a_header_that_was_not_there_is_new():
    rows = [
        [*BASE[0], "Stock"],
        [*BASE[1], "5"],
        [*BASE[2], "6"],
        [*BASE[3], "7"],
        [*BASE[4], "8"],
    ]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert [(c.new_index, c.header, c.new_type) for c in result.new] == [(4, "stock", "integer")]
    assert result.has_changes


def test_a_header_that_disappeared_is_missing():
    rows = [[row[0], row[1], row[2]] for row in BASE]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert [(c.saved_index, c.header, c.saved_type, c.used_by_plan) for c in result.missing] == [
        (3, "iva", "percent", False)
    ]


def plan_using_vat_column():
    profile = profile_sheet(BASE)
    roles = [R.CODE, R.DESCRIPTION, R.COST_PRICE, R.VAT_RATE]
    build = build_plan(
        [RoleAssignment(column, role) for column, role in zip(profile.columns, roles)],
        PlanParameters(
            "Ferreteria",
            price_includes_vat=True,
            price_is_per_pack=False,
            currency=ConstantSource("ARS"),
        ),
    )
    assert build.plan is not None
    return build.plan


def test_a_missing_column_is_flagged_when_the_plan_uses_it():
    rows = [[row[0], row[1], row[2]] for row in BASE]

    result = compare_fingerprint(
        saved_of(BASE), profile_sheet(rows), "Hoja1", plan_using_vat_column()
    )

    assert [(c.header, c.used_by_plan) for c in result.missing] == [("iva", True)]


def test_a_missing_column_the_plan_ignores_is_not_flagged():
    wide = [[*BASE[0], "Notas"], *[[*row, "n"] for row in BASE[1:]]]
    current = [row[:4] for row in wide]

    result = compare_fingerprint(
        saved_of(wide), profile_sheet(current), "Hoja1", plan_using_vat_column()
    )

    assert [(c.header, c.used_by_plan) for c in result.missing] == [("notas", False)]


def test_a_different_sheet_name_is_reported():
    result = compare_fingerprint(saved_of(BASE, sheet="Octubre"), profile_sheet(BASE), "Noviembre")

    assert result.sheet_change == ("Octubre", "Noviembre")
    assert result.has_changes


def test_the_sheet_name_is_not_compared_when_it_is_unknown():
    result = compare_fingerprint(saved_of(BASE, sheet="Octubre"), profile_sheet(BASE))

    assert result.sheet_change is None


def test_a_different_header_row_is_reported_even_when_columns_match():
    rows = [["LISTA DE PRECIOS", "", "", ""], *BASE]

    result = compare_fingerprint(saved_of(BASE), profile_sheet(rows), "Hoja1")

    assert result.header_row_change == (0, 1)
    assert result.has_changes
    assert len(result.unchanged) == 4


def test_duplicated_headers_pair_up_in_column_order():
    rows = [
        ["Codigo", "Precio", "Precio", "IVA"],
        ["A1", "1.210,00", "1.000,00", "21%"],
        ["A2", "968,00", "900,00", "21%"],
        ["A3", "121,00", "100,00", "21%"],
        ["A4", "60,50", "50,00", "21%"],
    ]
    shifted = [["Extra", *rows[0]], *[["x", *row] for row in rows[1:]]]

    result = compare_fingerprint(saved_of(rows), profile_sheet(shifted), "Hoja1")

    assert [(c.saved_index, c.new_index) for c in result.moved] == [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert [c.new_index for c in result.new] == [0]


def test_columns_without_a_header_only_match_the_same_position():
    rows = [["A1", "Tornillo", "10,50"], ["A2", "Tuerca", "11,50"], ["A3", "Clavo", "12,50"]]
    saved = fingerprint_of(profile_sheet(rows, header_row=None), "Hoja1")
    shifted_rows = [["x", *row] for row in rows]

    same = compare_fingerprint(saved, profile_sheet(rows, header_row=None), "Hoja1")
    shifted = compare_fingerprint(saved, profile_sheet(shifted_rows, header_row=None), "Hoja1")

    assert not same.has_changes
    # Without a header there is nothing to follow a column by: position is the only identity.
    assert shifted.moved == ()
    assert [c.saved_index for c in shifted.retyped] == [2]
    assert [c.new_index for c in shifted.new] == [3]
    assert shifted.missing == ()


@pytest.mark.parametrize(
    ("saved", "current", "compatible"),
    [
        ("integer", "decimal", True),
        ("decimal", "money", True),
        ("money", "integer", True),
        ("text", "code", True),
        ("code", "text", True),
        ("decimal", "text", False),
        ("percent", "decimal", False),
        ("barcode", "integer", False),
        ("date", "text", False),
        ("empty", "text", False),
        ("empty", "empty", True),
        ("text", "text", True),
    ],
)
def test_type_compatibility(saved, current, compatible):
    assert types_compatible(saved, current) is compatible


def test_comparison_accepts_a_hand_built_fingerprint():
    saved = SheetFingerprint(
        "Hoja1",
        0,
        (ColumnFingerprint(0, "codigo", "code"), ColumnFingerprint(1, "precio", "decimal")),
    )

    result = compare_fingerprint(
        saved, profile_sheet([["Codigo", "Precio"], ["A1", "10,5"], ["A2", "11,5"]])
    )

    assert not result.has_changes
