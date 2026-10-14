from pricor.domain.engine import execute_numbered_rows
from pricor.domain.plan import parse_plan
from pricor.domain.profile import engine_input, profile_sheet

from .golden import GOLDEN_HEADERS, golden_plan_dict

GOOD = ("00123 ", "  TORNILLO AUTOP.   8x1  ", "$ 12.100,00", "10", "10+5", "21%")
BAD_UNITS = ("00124", "ARANDELA", "$ 500,00", "0", "0", "21%")
BAD_PRICE = ("00125", "TUERCA", "abc", "10", "0", "21%")


def _sheet():
    return [
        ("LISTA DE PRECIOS", None, None, None, None, None),  # file row 1: preamble
        tuple(GOLDEN_HEADERS),  # file row 2
        ("FERRETERIA", None, None, None, None, None),  # file row 3: section
        GOOD,  # file row 4
        BAD_UNITS,  # file row 5
        (None,) * 6,  # file row 6: empty
        ("BULONES", None, None, None, None, None),  # file row 7: section
        BAD_PRICE,  # file row 8
        ("TOTAL", None, "1,00", None, None, None),  # file row 9: total
    ]


def test_engine_executes_profiler_pairs_with_real_file_row_numbers():
    rows = _sheet()
    headers, data = engine_input(rows, profile_sheet(rows))

    result = execute_numbered_rows(parse_plan(golden_plan_dict()), headers, data)

    assert [r.row_number for r in result.accepted] == [4]
    assert [r.row_number for r in result.rejected] == [5, 8]
    assert len(result.accepted) + len(result.rejected) == len(data) == 3
