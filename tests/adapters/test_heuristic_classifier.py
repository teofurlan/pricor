import pytest

from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier, normalize_header
from pricor.domain.profile import profile_sheet
from pricor.ports.column_classifier import ColumnClassification, ColumnRole

CODES = ["A-1001", "A-1002", "B-2210", "C-0042", "C-0043", "D-7"]
DESCRIPTIONS = [
    "TORNILLO AUTOPERFORANTE 8x1 CAJA",
    "ARANDELA PLANA GALVANIZADA 1/4",
    "TUERCA HEXAGONAL ZINCADA M8",
    "CABLE UNIPOLAR 2,5MM ROLLO X100",
    "LLAVE TERMICA BIPOLAR 20A",
    "PINTURA LATEX INTERIOR 20LT",
]
PRICES = ["1.234,50", "980,00", "15.200,10", "310,75", "45,00", "2.980,00"]
RETAIL = ["1.900,00", "1.400,00", "21.000,00", "480,00", "70,00", "4.100,00"]
EANS = [
    "7791234567890",
    "7799876543210",
    "7790001112223",
    "7794445556667",
    "7791112223334",
    "7798889990001",
]
VAT = ["21%", "10,5%", "21%", "21%", "10,5%", "21%"]
VAT_PLAIN = ["21", "10.5", "21", "21", "10.5", "21"]
UNITS = ["10", "100", "50", "1", "12", "6"]
DISCOUNTS = ["10+5", "0", "5", "10+5", "15", "0"]
CURRENCY = ["USD", "ARS", "ARS", "USD", "ARS", "ARS"]

classifier = HeuristicColumnClassifier()


def column(header, values):
    rows = [("pad", header)] + [(f"p{i}", value) for i, value in enumerate(values)]
    return profile_sheet(rows).columns[1]


def classify(header, values):
    return classifier.classify_column(column(header, values))


@pytest.mark.parametrize(
    ("header", "values", "role"),
    [
        ("Código", CODES, ColumnRole.CODE),
        ("Descripción", DESCRIPTIONS, ColumnRole.DESCRIPTION),
        ("Precio de lista", PRICES, ColumnRole.COST_PRICE),
        ("Precio sugerido de venta", RETAIL, ColumnRole.RETAIL_PRICE),
        ("IVA", VAT, ColumnRole.VAT_RATE),
        ("Unidades por bulto", UNITS, ColumnRole.UNITS_PER_PACK),
        ("EAN", EANS, ColumnRole.BARCODE),
        ("Descuento", DISCOUNTS, ColumnRole.DISCOUNT),
        ("Moneda", CURRENCY, ColumnRole.CURRENCY),
    ],
)
def test_each_role_is_recognised_from_header_and_values(header, values, role):
    result = classify(header, values)
    assert result.role is role
    assert result.score >= 0.6


@pytest.mark.parametrize(
    ("header", "values", "role"),
    [
        ("cód", CODES, ColumnRole.CODE),
        ("cod_prov", CODES, ColumnRole.CODE),
        ("descrip", DESCRIPTIONS, ColumnRole.DESCRIPTION),
        ("pcio", PRICES, ColumnRole.COST_PRICE),
        ("P. Lista", PRICES, ColumnRole.COST_PRICE),
        ("p.venta", RETAIL, ColumnRole.RETAIL_PRICE),
        ("Sugerido", RETAIL, ColumnRole.RETAIL_PRICE),
        ("bonif", DISCOUNTS, ColumnRole.DISCOUNT),
        ("DTO", DISCOUNTS, ColumnRole.DISCOUNT),
        ("alic", VAT, ColumnRole.VAT_RATE),
        ("iva", VAT_PLAIN, ColumnRole.VAT_RATE),
        ("U x B", UNITS, ColumnRole.UNITS_PER_PACK),
        ("UNID X BULTO", UNITS, ColumnRole.UNITS_PER_PACK),
        ("ean", EANS, ColumnRole.BARCODE),
        ("cod barra", EANS, ColumnRole.BARCODE),
        ("Cod. Barras", EANS, ColumnRole.BARCODE),
        ("mon", CURRENCY, ColumnRole.CURRENCY),
    ],
)
def test_abbreviations_and_spelling_variants(header, values, role):
    assert classify(header, values).role is role


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Cód.", "cod"),
        ("COD_PROV", "cod prov"),
        ("  p. lista ", "p lista"),
        ("Descripción  del   artículo", "descripcion del articulo"),
        ("c/IVA", "c iva"),
    ],
)
def test_header_normalization(header, expected):
    assert normalize_header(header) == expected


@pytest.mark.parametrize("header", ["Precio lista", "Costo", "Neto", "Precio mayorista"])
def test_cost_keywords_choose_cost_over_retail(header):
    assert classify(header, PRICES).role is ColumnRole.COST_PRICE


@pytest.mark.parametrize("header", ["Precio venta", "PVP", "Precio público", "Sugerido"])
def test_retail_keywords_choose_retail_over_cost(header):
    assert classify(header, RETAIL).role is ColumnRole.RETAIL_PRICE


def test_plain_price_header_leans_to_cost_with_lower_confidence_than_a_modifier():
    plain = classify("Precio", PRICES)
    explicit = classify("Precio lista", PRICES)
    assert plain.role is ColumnRole.COST_PRICE
    assert plain.score < explicit.score


def test_barcode_header_wins_over_the_generic_code_keyword():
    assert classify("Código de barras", EANS).role is ColumnRole.BARCODE


def test_desc_is_description_for_text_and_discount_for_percentages():
    assert classify("Desc", DESCRIPTIONS).role is ColumnRole.DESCRIPTION
    assert classify("Desc", VAT).role is ColumnRole.DISCOUNT


def test_header_that_contradicts_the_values_is_not_trusted():
    result = classify("Precio", DESCRIPTIONS)
    assert result.role is not ColumnRole.COST_PRICE


# -- header-less columns ----------------------------------------------------


def test_headerless_barcode_column_is_classified_from_type():
    assert classify("", EANS).role is ColumnRole.BARCODE


def test_headerless_description_column_is_classified_from_text_shape():
    assert classify("", DESCRIPTIONS).role is ColumnRole.DESCRIPTION


def test_headerless_code_column_is_classified_from_type():
    assert classify("", CODES).role is ColumnRole.CODE


def test_headerless_money_column_is_a_price_with_modest_confidence():
    result = classify("", [f"$ {price}" for price in PRICES])
    assert result.role in (ColumnRole.COST_PRICE, ColumnRole.RETAIL_PRICE)
    assert 0.3 <= result.score <= 0.6


def test_headerless_percent_column_is_vat_when_values_are_vat_rates():
    assert classify("", VAT).role is ColumnRole.VAT_RATE


def test_headerless_discount_chains_are_discounts():
    assert classify("", ["10+5", "5+5", "10", "10+5+3", "15", "10+5"]).role is ColumnRole.DISCOUNT


def test_headerless_currency_codes_are_currency():
    assert classify("", CURRENCY).role is ColumnRole.CURRENCY


def test_rationale_mentions_header_evidence_or_its_absence():
    assert "p lista" in classify("P. Lista", PRICES).rationale
    assert "header" in classify("", EANS).rationale.lower()


# -- unknowns and result shape ---------------------------------------------


def test_unknown_header_with_unremarkable_values_is_ignore_with_low_score():
    result = classify("Zxqv", ["a", "a", "b", "a", "b", "a"])
    assert result.role is ColumnRole.IGNORE
    assert result.score <= 0.2


@pytest.mark.parametrize("header", ["Stock", "Marca", "Rubro", "Fecha"])
def test_known_irrelevant_headers_are_ignore(header):
    assert classify(header, ["1", "2", "3", "4", "5", "6"]).role is ColumnRole.IGNORE


def test_result_carries_per_label_scores_in_unit_range_and_optional_latency():
    result = classify("Precio lista", PRICES)
    assert isinstance(result, ColumnClassification)
    assert set(result.scores) == set(ColumnRole)
    assert all(0.0 <= value <= 1.0 for value in result.scores.values())
    assert result.score == result.scores[result.role]
    assert max(result.scores, key=result.scores.get) is result.role
    assert result.latency_seconds is None


def test_classify_sheet_returns_one_result_per_column_in_order():
    rows = [("Código", "Descripción", "", "Precio lista")] + [
        (CODES[i], DESCRIPTIONS[i], EANS[i], PRICES[i]) for i in range(6)
    ]
    profile = profile_sheet(rows)
    results = classifier.classify_sheet(profile)
    assert [r.index for r in results] == [0, 1, 2, 3]
    assert [r.role for r in results] == [
        ColumnRole.CODE,
        ColumnRole.DESCRIPTION,
        ColumnRole.BARCODE,
        ColumnRole.COST_PRICE,
    ]


def test_role_set_is_the_closed_list():
    assert {role.value for role in ColumnRole} == {
        "code",
        "description",
        "cost_price",
        "retail_price",
        "vat_rate",
        "units_per_pack",
        "barcode",
        "discount",
        "currency",
        "ignore",
    }


# -- compact headers seen in real price lists -------------------------------


@pytest.mark.parametrize(
    ("header", "values", "role"),
    [
        ("codart", CODES, ColumnRole.CODE),
        ("cantxbulto", UNITS, ColumnRole.UNITS_PER_PACK),
        ("precio1", PRICES, ColumnRole.COST_PRICE),
        ("dto1", DISCOUNTS, ColumnRole.DISCOUNT),
    ],
)
def test_compact_headers_are_split_or_listed(header, values, role):
    result = classify(header, values)
    assert result.role is role
    assert result.score >= 0.6


def test_digits_are_separated_from_letters_when_normalizing():
    assert normalize_header("Precio2") == "precio 2"


def test_classification_words_suppress_description_keywords():
    result = classify("Categoría del producto", DESCRIPTIONS)
    assert result.role is ColumnRole.IGNORE
