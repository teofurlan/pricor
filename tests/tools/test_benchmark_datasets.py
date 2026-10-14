from pricor.domain.profile import profile_sheet
from tools.benchmark.datasets import SheetCase, chunk_columns, held_out_cases

ROWS = (
    ("Codigo", "Detalle", "Costo"),
    ("A1", "Tornillo", "10,5"),
    ("A2", "Tuerca", "20,0"),
    ("A3", "Arandela", "30,5"),
)


def test_columns_are_regrouped_into_numbered_pseudo_sheets_in_a_reproducible_order():
    columns = profile_sheet(ROWS).columns * 3  # nine columns, indexes repeat

    first = chunk_columns(columns, size=4, seed=1)
    again = chunk_columns(columns, size=4, seed=1)

    assert [len(sheet.columns) for sheet, _ in first] == [4, 4, 1]
    assert all([c.index for c in sheet.columns] == list(range(len(sheet.columns))) for sheet, _ in first)
    assert [positions for _, positions in first] == [positions for _, positions in again]


def test_every_column_is_in_exactly_one_pseudo_sheet_and_its_position_is_kept():
    columns = profile_sheet(ROWS).columns * 3

    chunks = chunk_columns(columns, size=4, seed=1)

    seen = sorted(position for _, positions in chunks for position in positions)
    assert seen == list(range(9))
    for sheet, positions in chunks:
        assert [c.raw_header for c in sheet.columns] == [columns[p].raw_header for p in positions]


def test_a_held_out_case_pairs_each_labeled_column_with_its_role():
    case = SheetCase("acme-1", "S", profile_sheet(ROWS), {0: "code", 2: "cost_price"})

    assert case.expected_in_order() == [(0, "code"), (2, "cost_price")]
