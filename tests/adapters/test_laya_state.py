"""The text a column becomes before Laya reads it. Training and inference must share it."""

from pricor.adapters.laya_state import (
    MAX_SAMPLES,
    NO_HEADER,
    QUESTION_ID,
    QUESTIONS,
    column_stats,
    serialize_column,
    state_for_column,
)
from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole


def test_a_column_serializes_header_type_samples_and_stats():
    text = serialize_column("Precio Lista", "decimal", ["10,50", "20", "30,25"])

    assert text == (
        "Column header: Precio Lista\n"
        "Column type: decimal\n"
        "Sample values: 10,50 | 20 | 30,25\n"
        "Stats: numeric=3/3 min=10.5 max=30.25 avg_len=4.0 distinct=3"
    )


def test_a_header_less_column_says_so():
    assert "Column header: " + NO_HEADER in serialize_column("", "text", ["x"])
    assert "Column header: " + NO_HEADER in serialize_column("   ", "text", ["x"])


def test_only_the_first_samples_are_kept():
    values = [str(i) for i in range(20)]

    text = serialize_column("n", "integer", values)

    assert text.count(" | ") == MAX_SAMPLES - 1
    assert "numeric=5/5" in text


def test_untrusted_cell_text_is_flattened_and_truncated():
    text = serialize_column("Desc\nripcion", "text", ["line one\nline two\t" + "x" * 200])

    assert len(text.splitlines()) == 4  # header, type, samples, stats: no injected extra lines
    assert "x" * 100 not in text


def test_stats_read_currency_marks_and_decimal_commas():
    assert column_stats(["$1.5", "2,5", "abc"]).startswith("numeric=2/3 min=1.5 max=2.5")
    assert column_stats([]) == "numeric=0/0"


def test_stats_do_not_read_codes_with_letters_as_numbers():
    assert column_stats(["K44260X", "A-12", "12 kg"]).startswith("numeric=0/3")


def test_stats_read_grouped_thousands_and_percents():
    assert column_stats(["1.234,56", "$ 2.000", "10,5 %"]).startswith("numeric=3/3 min=10.5 max=2000")


def test_a_profiled_column_uses_its_raw_header_type_and_samples():
    sheet = profile_sheet([("Codigo", "Precio"), ("A1", "10,5"), ("A2", "20,5")])

    code, price = (state_for_column(column) for column in sheet.columns)

    assert code.startswith("Column header: Codigo\nColumn type: code\nSample values: A1 | A2")
    assert price.startswith("Column header: Precio\nColumn type: decimal\n")


def test_the_same_column_always_gives_the_same_text():
    sheet = profile_sheet([("a", "b"), ("1", "x"), ("2", "y")])

    assert [state_for_column(c) for c in sheet.columns] == [state_for_column(c) for c in sheet.columns]


def test_the_question_offers_exactly_the_ten_closed_roles():
    criteria = QUESTIONS[QUESTION_ID]["criteria"]

    assert set(criteria) == {role.value for role in ColumnRole}
    assert QUESTIONS[QUESTION_ID]["type"] == "choice"
