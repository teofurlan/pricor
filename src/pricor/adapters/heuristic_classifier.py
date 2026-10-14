"""Keyword and type heuristics implementing the `ColumnClassifier` port.

Lives in `adapters/` (not the domain) because it is one interchangeable
implementation of the port, benchmarked against model-based ones; the Spanish
keyword table is a policy choice, not a domain rule. It has no dependencies.

For each role the score combines two independent signals:

* header evidence `h`: how strongly the normalized header matches the role's
  keywords (accents, case and punctuation stripped, so `Cód.`, `COD_PROV` and
  `p. lista` become `cod`, `cod prov` and `p lista`);
* type evidence: `fit` says whether the profile's apparent type and samples can
  hold that role at all, and `prior` says how likely the role is from the
  values alone (what lets header-less columns be classified).

`score = h * fit`, lifted a little by `prior`; with no header match the prior
alone decides, discounted when the header names some other role. Anything
whose best score stays under `MIN_SCORE` is `ignore` with a low score.
"""

import re
import unicodedata
from decimal import Decimal

from pricor.domain.parsing import CellError, parse_number
from pricor.domain.profile import ColumnProfile, ColumnType, SheetProfile
from pricor.ports.column_classifier import ColumnClassification, ColumnRole

R = ColumnRole

MIN_SCORE = 0.3
_IGNORE_BASELINE = 0.1
_VAT_LIKE_RATES = frozenset(Decimal(v) for v in ("0", "2.5", "5", "10.5", "21", "27"))
_DISCOUNT_CHAIN = re.compile(r"\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)+")
_CURRENCY_WORDS = frozenset({"usd", "ars", "eur", "$", "u$s", "us$", "u$d", "ar$", "dolar", "peso"})

# Keyword tables: tuples of normalized tokens, `*` suffix = prefix match.
_KEYWORDS: dict[ColumnRole, dict[tuple[str, ...], float]] = {
    R.CODE: {
        ("codigo",): 0.9, ("cod",): 0.85, ("cod", "prov"): 0.95, ("codigo", "prov*"): 0.95,
        ("sku",): 0.95, ("ref",): 0.7, ("referencia",): 0.8, ("art",): 0.5, ("item",): 0.6,
        ("id",): 0.6, ("cod", "art*"): 0.95, ("codigo", "art*"): 0.95, ("codart",): 0.95,
    },
    R.DESCRIPTION: {
        ("descrip*",): 0.95, ("descr",): 0.9, ("detalle",): 0.85, ("producto",): 0.8,
        ("prod",): 0.6, ("articulo",): 0.75, ("nombre",): 0.8, ("denominacion",): 0.85,
        ("desc",): 0.5, ("concepto",): 0.6,
    },
    R.VAT_RATE: {
        ("iva",): 0.9, ("alic*",): 0.9, ("impuesto",): 0.7, ("i", "v", "a"): 0.9,
    },
    R.UNITS_PER_PACK: {
        ("u", "x", "b"): 0.95, ("uxb",): 0.95, ("unid*", "x", "bulto"): 0.95,
        ("un", "x", "bulto"): 0.95, ("cantxbulto",): 0.95, ("cantxb",): 0.95, ("bulto",): 0.8, ("pack",): 0.7, ("caja",): 0.6,
        ("cantidad",): 0.5, ("cant",): 0.5, ("unidades",): 0.6, ("presentacion",): 0.6,
        ("contenido",): 0.5,
    },
    R.BARCODE: {
        ("ean*",): 0.95, ("barcode",): 0.95, ("cod", "barra*"): 0.95,
        ("codigo", "barra*"): 0.95, ("gtin",): 0.95, ("upc",): 0.95, ("barra*",): 0.85,
        ("cb",): 0.6,
    },
    R.DISCOUNT: {
        ("dto*",): 0.95, ("descuento*",): 0.95, ("bonif*",): 0.95, ("desc",): 0.5,
        ("rebaja",): 0.8, ("off",): 0.5,
    },
    R.CURRENCY: {
        ("moneda",): 0.95, ("mon",): 0.8, ("divisa",): 0.9, ("currency",): 0.9,
    },
    R.IGNORE: {
        ("stock*",): 0.7, ("marca",): 0.7, ("rubro",): 0.7, ("linea",): 0.7,
        ("familia",): 0.7, ("categoria",): 0.7, ("fecha",): 0.7, ("obs*",): 0.7,
        ("imagen",): 0.7, ("foto",): 0.7, ("link",): 0.7, ("url",): 0.7, ("peso",): 0.6,
        ("disponible",): 0.6,
    },
}  # fmt: skip

_PRICE_WORDS = frozenset({"precio", "precios", "pcio", "prec", "pr", "p", "importe", "valor", "monto"})
_COST_MODIFIERS = frozenset(
    {"lista", "costo", "neto", "mayorista", "mayor", "compra", "distribuidor", "dist"}
)
_RETAIL_MODIFIERS = frozenset(
    {"venta", "sugerido", "sugerida", "publico", "pvp", "minorista", "pv", "recomendado", "final"}
)
_PLAIN_PRICE = {R.COST_PRICE: 0.5, R.RETAIL_PRICE: 0.3}


def normalize_header(raw: str) -> str:
    """Lower-case, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", raw)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    spaced = re.sub(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", " ", stripped.casefold())
    return " ".join(re.sub(r"[^a-z0-9$]+", " ", spaced).split())


def _token_matches(pattern: str, token: str) -> bool:
    return token.startswith(pattern[:-1]) if pattern.endswith("*") else token == pattern


def _phrase_in(phrase: tuple[str, ...], tokens: list[str]) -> bool:
    size = len(phrase)
    return any(
        all(_token_matches(p, t) for p, t in zip(phrase, tokens[i : i + size], strict=True))
        for i in range(len(tokens) - size + 1)
    )


def _header_evidence(header: str) -> dict[ColumnRole, tuple[float, str]]:
    """Per-role header strength with the keyword that produced it."""
    tokens = header.split()
    found: dict[ColumnRole, tuple[float, str]] = {}
    for role, table in _KEYWORDS.items():
        for phrase, weight in table.items():
            if _phrase_in(phrase, tokens) and weight > found.get(role, (0.0, ""))[0]:
                found[role] = (weight, " ".join(phrase).replace("*", ""))
    if R.BARCODE in found and found[R.BARCODE][0] >= 0.85:
        found.pop(R.CODE, None)  # "cod barra" is a barcode, not a supplier code
    if found.get(R.IGNORE, (0.0, ""))[0] >= 0.7:
        # "categoria del producto" classifies the product; it is not its description
        found.pop(R.DESCRIPTION, None)
        found.pop(R.CODE, None)

    token_set = set(tokens)
    retail = token_set & _RETAIL_MODIFIERS
    cost = token_set & _COST_MODIFIERS
    price = token_set & _PRICE_WORDS
    if retail:
        found[R.RETAIL_PRICE] = (0.95 if price else 0.9, sorted(retail)[0])
    elif cost:
        found[R.COST_PRICE] = (0.95 if price else 0.9, sorted(cost)[0])
    elif price:
        word = sorted(price)[0]
        found[R.COST_PRICE] = (_PLAIN_PRICE[R.COST_PRICE], word)
        found[R.RETAIL_PRICE] = (_PLAIN_PRICE[R.RETAIL_PRICE], word)
    return found


def _numbers(column: ColumnProfile) -> list[Decimal]:
    """Numeric values among the samples, read under the detected format."""
    fmt = column.number_format
    decimal_sep = (fmt.decimal_sep if fmt else None) or "."
    thousands_sep = (fmt.thousands_sep if fmt else None) or ""
    texts = list(column.samples) + [s.value for s in column.atypical if s.kind in ("min", "max")]
    values: list[Decimal] = []
    for text in texts:
        try:
            values.append(parse_number(text.replace("%", "").strip(), decimal_sep, thousands_sep))
        except CellError:
            continue
    return values


def _is_discount_text(text: str) -> bool:
    return bool(_DISCOUNT_CHAIN.fullmatch(text.strip()))


class _Shape:
    """Facts about a column's values that the fit and prior rules need."""

    def __init__(self, column: ColumnProfile):
        self.type = column.apparent_type
        self.samples = column.samples
        numbers = _numbers(column) if self.type in _NUMERIC else []
        self.numbers = numbers
        self.small = bool(numbers) and all(0 <= n <= 100 for n in numbers)
        self.vat_like = bool(numbers) and all(n in _VAT_LIKE_RATES for n in numbers)
        self.discount_text = bool(self.samples) and any(
            _is_discount_text(s) for s in self.samples
        ) and all(_is_discount_text(s) or _plain_small(s) for s in self.samples)
        self.avg_length = (
            sum(len(s) for s in self.samples) / len(self.samples) if self.samples else 0.0
        )
        self.currency_text = bool(self.samples) and all(
            s.strip().casefold() in _CURRENCY_WORDS for s in self.samples
        )
        self.distinct = column.distinct_ratio


_NUMERIC = frozenset({ColumnType.INTEGER, ColumnType.DECIMAL, ColumnType.MONEY, ColumnType.PERCENT})


def _plain_small(text: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}(?:[.,]\d+)?", text.strip()))


def _fit(role: ColumnRole, s: _Shape) -> float:
    t = s.type
    if t is ColumnType.EMPTY:
        return 0.0
    if role in (R.COST_PRICE, R.RETAIL_PRICE):
        return {
            ColumnType.MONEY: 1.0, ColumnType.DECIMAL: 1.0, ColumnType.INTEGER: 0.8,
            ColumnType.TEXT: 0.1, ColumnType.CODE: 0.1, ColumnType.BARCODE: 0.2,
        }.get(t, 0.0)  # fmt: skip
    if role is R.CODE:
        return {
            ColumnType.CODE: 1.0, ColumnType.TEXT: 0.8, ColumnType.INTEGER: 0.9,
            ColumnType.BARCODE: 0.6,
        }.get(t, 0.1)  # fmt: skip
    if role is R.DESCRIPTION:
        return {ColumnType.TEXT: 1.0, ColumnType.CODE: 0.4}.get(t, 0.1)
    if role is R.VAT_RATE:
        if t is ColumnType.PERCENT:
            return 1.0
        if t in _NUMERIC:
            return (0.2 if t is ColumnType.MONEY else 0.9) if s.small else 0.1
        return 0.1
    if role is R.DISCOUNT:
        if t is ColumnType.PERCENT:
            return 1.0
        if s.discount_text:
            return 1.0
        if t in _NUMERIC:
            return 0.8 if s.small else 0.1
        return 0.2
    if role is R.UNITS_PER_PACK:
        if t is ColumnType.INTEGER:
            return 1.0 if all(n <= 10000 for n in s.numbers) else 0.4
        return {ColumnType.DECIMAL: 0.6, ColumnType.CODE: 0.3}.get(t, 0.1)
    if role is R.BARCODE:
        return {
            ColumnType.BARCODE: 1.0, ColumnType.CODE: 0.9, ColumnType.INTEGER: 0.8,
            ColumnType.TEXT: 0.5,
        }.get(t, 0.1)  # fmt: skip
    if role is R.CURRENCY:
        if s.currency_text:
            return 1.0
        return 0.7 if t in (ColumnType.TEXT, ColumnType.CODE) and s.avg_length <= 5 else 0.1
    return 1.0  # ignore


def _priors(s: _Shape) -> dict[ColumnRole, float]:
    t = s.type
    if t in (ColumnType.EMPTY, ColumnType.DATE):
        return {R.IGNORE: 0.8}
    if t is ColumnType.BARCODE:
        return {R.BARCODE: 0.85}
    if t is ColumnType.PERCENT:
        if s.vat_like:
            return {R.VAT_RATE: 0.55, R.DISCOUNT: 0.35}
        return {R.DISCOUNT: 0.55, R.VAT_RATE: 0.3}
    if t is ColumnType.MONEY:
        return {R.COST_PRICE: 0.45, R.RETAIL_PRICE: 0.3}
    if t is ColumnType.DECIMAL:
        return {R.COST_PRICE: 0.4, R.RETAIL_PRICE: 0.25}
    if t is ColumnType.INTEGER:
        return {R.UNITS_PER_PACK: 0.3}
    if t is ColumnType.CODE:
        return {R.CODE: 0.55} if s.distinct >= 0.9 else {}
    if t is ColumnType.TEXT:
        if s.discount_text:
            return {R.DISCOUNT: 0.6}
        if s.currency_text:
            return {R.CURRENCY: 0.7}
        if s.avg_length >= 12 and s.distinct >= 0.7:
            return {R.DESCRIPTION: 0.65}
    return {}


def _rationale(role: ColumnRole, header: str, keyword: str | None, s: _Shape, prior: float) -> str:
    if role is R.IGNORE and keyword is None and prior == 0.0:
        return "no keyword in the header and the values match no role"
    if keyword and header:
        evidence = f"header '{header}' matches keyword '{keyword}'"
    elif header:
        evidence = f"header '{header}' has no matching keyword"
    else:
        evidence = "no header text"
    return f"{evidence}; column looks {s.type.value}" + (
        "; values alone suggest this role" if prior >= MIN_SCORE else ""
    )


class HeuristicColumnClassifier:
    """Classify columns from normalized Spanish headers plus profile type evidence."""

    def classify_column(
        self, column: ColumnProfile, sheet: SheetProfile | None = None
    ) -> ColumnClassification:
        header = normalize_header(column.raw_header)
        evidence = _header_evidence(header)
        shape = _Shape(column)
        priors = _priors(shape)
        named_other = any(role is not R.IGNORE for role in evidence)

        scores: dict[ColumnRole, float] = {}
        for role in ColumnRole:
            strength = evidence.get(role, (0.0, ""))[0]
            prior = priors.get(role, 0.0)
            if strength > 0:
                base = strength * _fit(role, shape)
                score = base + (1 - base) * 0.5 * prior
            else:
                score = prior * (0.85 if named_other else 1.0)
            scores[role] = round(min(1.0, score), 3)
        scores[R.IGNORE] = max(scores[R.IGNORE], _IGNORE_BASELINE)

        best = max(ColumnRole, key=lambda role: (scores[role], role is not R.IGNORE))
        if best is not R.IGNORE and scores[best] < MIN_SCORE:
            best = R.IGNORE
        keyword = evidence.get(best, (0.0, None))[1]
        rationale = _rationale(best, header, keyword, shape, priors.get(best, 0.0))
        return ColumnClassification(
            index=column.index,
            header=column.raw_header,
            role=best,
            score=scores[best],
            rationale=rationale,
            scores=scores,
        )

    def classify_sheet(self, sheet: SheetProfile) -> list[ColumnClassification]:
        return [self.classify_column(column, sheet) for column in sheet.columns]
