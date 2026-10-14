"""Seeded synthetic price-list columns: Spanish header variants and role-shaped values.

The generator never emits a header whose normalized form is in `banned` (the headers of the
held-out distributors). Spelling variants change only case, spacing, punctuation and accents,
which normalization removes, so filtering the vocabulary once is enough to guarantee it.

Synthetic examples are labeled synthetic downstream; they are not evidence about real lists.
"""

import random
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pricor.domain.roles import ColumnRole

from .split import normalize_header

HEADERLESS_RATE = 0.12
MIN_ROWS, MAX_ROWS = 20, 40

_CODE = (
    "Código", "Codigo", "Cód.", "Cod.", "COD", "Cod Art.", "Código Artículo", "Artículo", "Art.",
    "Ref.", "Referencia", "SKU", "N° Art", "Nro Parte", "Cod. Prov", "Código Proveedor", "Item",
    "codart", "codigo_art", "cod_prov", "CodInterno", "Código Producto", "Part Number",
    "Cód. Fabricante", "ID Producto", "Cod. Artículo",
)
_DESCRIPTION = (
    "Descripción", "Descripcion", "Detalle", "Producto", "Nombre", "Denominación", "Desc.",
    "Descrip.", "Artículo - Detalle", "Detalle Producto", "nombre", "descrip", "desc_art",
    "Descripción Artículo", "Nombre Producto", "Título", "Articulo Descripcion",
)
_COST_BASES = ("Precio", "Pcio", "P.")
_COST_MODIFIERS = ("Lista", "Costo", "Neto", "Mayorista", "s/IVA", "Compra", "Unit. Neto")
_COST = (
    "P. Lista", "Lista", "Costo", "Neto", "P.Mayorista", "Precio de Lista", "Precio", "Precios",
    "precio1", "precio2", "pcio", "Importe Unitario", "Pcio. Costo",
)
_RETAIL_MODIFIERS = ("Público", "Sugerido", "Final", "Venta Público", "Consumidor", "c/IVA", "PVP")
_RETAIL = (
    "PVP", "P.V.P.", "Pcio c/IVA", "Precio Final", "P. Venta", "Venta", "P. Sugerido", "Sugerido",
    "Sugerido Público", "Precio Consumidor", "Final c/IVA", "Pcio Vta", "pvp1", "Precio al Público",
    "Precio Sugerido al Publico", "Precio Venta",
)
_VAT = (
    "IVA", "% IVA", "Alíc. IVA", "Alicuota IVA", "Alic. IVA %", "I.V.A.", "Tasa IVA", "IVA %",
    "Alicuota", "porc_iva", "Impuesto IVA",
)
_UNITS = (
    "Unid x bulto", "Unidades x Bulto", "U x Caja", "Bulto", "Un/Bulto", "Cant. x Pack",
    "Embalaje", "Und. por Caja", "UxB", "Pack", "Cantidad por bulto", "X Caja", "cantxbulto",
    "cant_bulto", "Unidades por Caja", "Cant Bulto", "Presentación", "Uni x Pack",
)
_BARCODE = (
    "EAN", "EAN13", "Cód. Barras", "Codigo de Barras", "Cod Barra", "Barras", "UPC", "Código EAN",
    "COD. BARRAS", "GTIN", "codbarras", "Código de barras", "EAN-13",
)
_DISCOUNT = (
    "Bonif.", "Bonificación", "Dto.", "Descuento", "% Dto", "Desc. x cant", "Dto x Cantidad",
    "BONIF %", "Descto.", "Oferta %", "Bonif. x vol.", "dto_cant", "Descuento por Volumen",
    "% Desc.",
)
_CURRENCY = (
    "Moneda", "Mon.", "Divisa", "Tipo Moneda", "MON", "Moneda Precio", "Moneda Lista", "Cotiz.",
    "moneda_precio", "Divisa Precio",
)
_IGNORE = (
    "Marca", "Rubro", "Familia", "Rubro / Línea", "Subrubro", "Categoría", "Observaciones",
    "Obs.", "Notas", "Stock", "Proveedor", "Origen", "Línea", "Peso", "Fecha Act.", "Estado",
    "Unidad", "Oferta?", "Agrupador", "Color", "Cantidad", "Importe", "Orden", "Cant. Pedido",
    "Última Modificación", "Activo", "interno", "cambio", "Sección", "Capítulo", "Stock Disponible",
    "Fecha",
)


def _composed(bases: Sequence[str], modifiers: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"{base} {modifier}" for base in bases for modifier in modifiers)


VOCABULARY: dict[ColumnRole, tuple[str, ...]] = {
    ColumnRole.CODE: _CODE,
    ColumnRole.DESCRIPTION: _DESCRIPTION,
    ColumnRole.COST_PRICE: _COST + _composed(_COST_BASES, _COST_MODIFIERS),
    ColumnRole.RETAIL_PRICE: _RETAIL + _composed(("Precio", "Pcio"), _RETAIL_MODIFIERS),
    ColumnRole.VAT_RATE: _VAT,
    ColumnRole.UNITS_PER_PACK: _UNITS,
    ColumnRole.BARCODE: _BARCODE,
    ColumnRole.DISCOUNT: _DISCOUNT,
    ColumnRole.CURRENCY: _CURRENCY,
    ColumnRole.IGNORE: _IGNORE,
}


@dataclass(frozen=True)
class SyntheticColumn:
    header: str  # "" for a header-less column
    role: ColumnRole
    values: tuple[str, ...]  # "" is an empty cell


# -- header spelling -------------------------------------------------------------


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _spell(header: str, rng: random.Random) -> str:
    """A spelling variant with the same normalized form."""
    variants: list[Callable[[str], str]] = [
        lambda h: h,
        lambda h: h.upper(),
        lambda h: h.lower(),
        lambda h: h.title(),
        _strip_accents,
        lambda h: re.sub(r"\s+", "_", h),
        lambda h: f" {h} ",
    ]
    return rng.choice(variants)(header)


# -- values ----------------------------------------------------------------------

_WORDS = (
    "TORNILLO", "CABLE", "LLAVE", "MARTILLO", "LAMPARA LED", "CINTA AISLADORA", "PINTURA",
    "TUERCA", "DISCO CORTE", "GUANTE", "SOLDADORA", "BROCA", "SILICONA", "TAPON", "CODO PVC",
    "TERMICA", "CUADERNO", "LAPICERA", "MOCHILA", "AURICULAR",
)
_BRANDS = ("TOTH", "FABI", "PROLL", "3M", "STANLEY", "SICA", "PHILIPS", "BOSCH", "FILIZOLA", "MAZZUCA")
_CATEGORIES = ("FERRETERIA", "ELECTRICIDAD", "LIBRERIA", "BULONERIA", "SANITARIOS", "Rubro 12")
_SPECS = ("N° {n}", "x{n}mm", "{n}W", "ref {n}")


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def _code(rng: random.Random, n: int) -> list[str]:
    style = rng.choice(["A%d", "BR-%d", "K%dX", "%05d", "%d", "FPI%05d", "dotted", "mixed"])
    if style == "dotted":
        return [f"{rng.randint(1, 300)}.{rng.randint(1, 20)}.{rng.randint(1, 200)}" for _ in range(n)]
    if style == "mixed":
        return [
            rng.choice("ABCDEFGH") + rng.choice("ABCDEFGH") + _digits(rng, rng.randint(2, 5))
            for _ in range(n)
        ]
    return [style % rng.randint(1, 99999) for _ in range(n)]


def _description(rng: random.Random, n: int) -> list[str]:
    return [
        f"{rng.choice(_WORDS)} {rng.choice(_SPECS).format(n=rng.randint(2, 50))}" for _ in range(n)
    ]


def _grouped(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _price(rng: random.Random, n: int) -> list[str]:
    style = rng.choice(["point", "comma", "thousands", "integer", "money", "money_comma"])
    out = []
    for _ in range(n):
        amount = rng.uniform(5, 90000)
        out.append(
            {
                "point": f"{amount:.2f}",
                "comma": f"{amount:.2f}".replace(".", ","),
                "thousands": _grouped(amount),
                "integer": str(int(amount)),
                "money": f"${amount:.3f}",
                "money_comma": "$ " + _grouped(amount),
            }[style]
        )
    return out


def _percent(rng: random.Random, n: int, pool: Sequence[str]) -> list[str]:
    suffix = rng.choice(["", "%", " %"])
    return [rng.choice(pool).replace(".", rng.choice([".", ","])) + suffix for _ in range(n)]


def _ignored(rng: random.Random, n: int) -> list[str]:
    kind = rng.choice(["brand", "category", "flag", "date", "number", "empty", "sign"])
    if kind == "empty":
        return [""] * n
    if kind == "number":
        return [str(rng.randint(0, 500)) for _ in range(n)]
    pools = {
        "brand": _BRANDS,
        "category": _CATEGORIES,
        "flag": ("SI", "NO", "TRUE", "S", "N"),
        "date": ("2026-03-01", "15/09/2026", "2026-09-30T10:00:00"),
        "sign": ("+", "-", "="),
    }
    return [rng.choice(pools[kind]) for _ in range(n)]


def _values(role: ColumnRole, rng: random.Random, n: int) -> list[str]:
    match role:
        case ColumnRole.CODE:
            return _code(rng, n)
        case ColumnRole.DESCRIPTION:
            return _description(rng, n)
        case ColumnRole.COST_PRICE | ColumnRole.RETAIL_PRICE:
            return _price(rng, n)
        case ColumnRole.VAT_RATE:
            return _percent(rng, n, ("21", "10.5", "21.00", "27", "0", "10.50"))
        case ColumnRole.UNITS_PER_PACK:
            pool = ("1", "6", "10", "12", "24", "50", "100", "144", "x 12", "caja x 20")
            return [rng.choice(pool) for _ in range(n)]
        case ColumnRole.BARCODE:
            return [rng.choice(["779", "780", "790"]) + _digits(rng, 10) for _ in range(n)]
        case ColumnRole.DISCOUNT:
            pool = ("10", "5%", "15", "0", "10% x 10 UN", "20% x 5", "7.5", "3+1", "10+5", "5+5+2")
            return [rng.choice(pool) for _ in range(n)]
        case ColumnRole.CURRENCY:
            pair = rng.choice(
                [("$", "u$s"), ("ARS", "USD"), ("Pesos", "Dolares"), ("$", "U$S"), ("$", "$"), ("USD", "USD")]
            )
            return [rng.choice(pair) for _ in range(n)]
    return _ignored(rng, n)


# -- generation ------------------------------------------------------------------


def generate_columns(
    count: int, seed: int, banned: frozenset[str], headerless_rate: float = HEADERLESS_RATE
) -> list[SyntheticColumn]:
    """`count` columns, roles in rotation, headers outside `banned` (normalized), seeded.

    The empty header is never banned: header-less columns are generated for every role at
    `headerless_rate`.
    """
    rng = random.Random(seed)
    pools: dict[ColumnRole, list[str]] = {}
    for role, words in VOCABULARY.items():
        pool = [word for word in words if normalize_header(word) not in banned]
        if not pool:
            raise ValueError(f"every {role.value} header is banned; the generator has nothing to say")
        pools[role] = pool
    roles = list(ColumnRole)
    columns = []
    for i in range(count):
        role = roles[i % len(roles)]
        header = "" if rng.random() < headerless_rate else _spell(rng.choice(pools[role]), rng)
        columns.append(
            SyntheticColumn(header, role, tuple(_values(role, rng, rng.randint(MIN_ROWS, MAX_ROWS))))
        )
    return columns
