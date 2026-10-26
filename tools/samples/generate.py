"""Generate the synthetic sample price lists in `src/pricor/samples/`.

    uv run python tools/samples/generate.py

A fictional Argentine hardware and electrical distributor, two weeks of lists. No network,
no third-party data, and the output is byte-for-byte reproducible: a fixed seed, fixed
workbook properties and fixed ZIP timestamps.
"""

import io
import random
import re
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import product
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from pricor.samples import SAMPLES, SAMPLES_DIR

SEED = 20261026
FIXED_TIME = datetime(2026, 1, 1)
ZIP_TIME = (2026, 1, 1, 0, 0, 0)
_FIXED_STAMP = FIXED_TIME.strftime("%Y-%m-%dT%H:%M:%SZ")
_MODIFIED = re.compile(r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")
HEADER = [
    "CODIGO", "COD_PROV", "DESCRIPCION", "MARCA", "UNIDAD",
    "PRECIO SIN IVA", "MONEDA", "IVA", "DTO.", "DTO X CANT",
]
HEADER_ROW = 5  # one-based: title, subtitle and two blank rows come first
BRANDS = ("Norte", "Andes", "Pampa", "Delta", "Sur", "Atlas")
PRODUCTS_PER_SECTION = 38
NEW_PRODUCTS = 4
DROPPED_PRODUCTS = 4
QUANTITY_OFFERS = ((5, 6), (10, 10), (10, 12), (15, 20))


@dataclass(frozen=True)
class Category:
    section: str
    prefix: str
    unit: str
    templates: tuple[str, ...]
    options: tuple[tuple[str, ...], ...]
    price_range: tuple[int, int]
    dollars: float  # share of the products priced in u$s


CATEGORIES = (
    Category("ILUMINACIÓN", "IL", "UN", ("Lámpara LED {} {}", "Tubo LED {} {}"),
             (("5W", "7W", "9W", "12W", "15W", "18W", "24W"), ("cálida", "fría", "neutra")),
             (900, 9000), 0.1),
    Category("CABLES Y CONDUCTORES", "CA", "MT", ("Cable unipolar {} {}", "Cable taller {} {}"),
             (("1,5 mm", "2,5 mm", "4 mm", "6 mm", "10 mm"),
              ("rojo", "azul", "negro", "verde", "celeste", "marrón", "bicolor")),
             (700, 6500), 0.0),
    Category("INTERRUPTORES Y TOMAS", "IN", "UN", ("Tecla {} {}", "Toma {} {}", "Módulo {} {}"),
             (("simple", "doble", "triple", "combinada", "bipolar", "tripolar"),
              ("blanco", "negro", "gris", "marfil", "aluminio")),
             (1200, 15000), 0.0),
    Category("PROTECCIONES", "PR", "UN", ("Llave térmica {} {}", "Disyuntor {} {}"),
             (("1x10A", "1x16A", "2x20A", "2x32A", "3x25A", "3x40A", "2x63A"),
              ("curva C", "curva B", "4,5 kA", "6 kA")),
             (6500, 98000), 0.15),
    Category("HERRAMIENTAS", "HE", "UN", ("Destornillador {} {}", "Pinza {} {}", "Llave {} {}"),
             (("plano", "Phillips", "universal", "combinada", "punta", "ajustable", "tubo"),
              ("6 mm", "8 mm", "10 mm", "13 mm", "17 mm", "19 mm")),
             (1800, 42000), 0.05),
    Category("TORNILLERÍA", "TO", "CAJA", ("Tornillo {} {}", "Bulón {} {}", "Tuerca {} {}"),
             (("hexagonal", "parker", "autoperforante", "fijación", "cabeza fresada", "mariposa"),
              ("M4", "M5", "M6", "M8", "M10", "1/4", "5/16")),
             (1500, 28000), 0.0),
    Category("AUTOMATIZACIÓN", "AU", "UN", ("Sensor {} {}", "Relé {} {}", "Temporizador {} {}"),
             (("de movimiento", "crepuscular", "de presencia", "magnético", "inalámbrico",
               "digital", "analógico"),
              ("12 V", "24 V", "220 V", "IP65")),
             (4, 140), 0.9),
    Category("CAÑERÍAS Y ACCESORIOS", "CN", "UN", ("Caño {} {}", "Codo {} {}", "Cupla {} {}"),
             (("corrugado", "rígido", "flexible", "galvanizado", "PVC", "termofusión"),
              ("3/4", "1", "1 1/4", "1 1/2", "2", "3")),
             (800, 21000), 0.0),
)
SECTION_ORDER = {category.section: index for index, category in enumerate(CATEGORIES)}


@dataclass(frozen=True)
class Item:
    section: str
    internal_code: str
    supplier_code: str
    description: str
    brand: str
    unit: str
    price: float
    currency: str
    vat: str
    discount: str
    quantity_discount: str


def _build_catalog() -> list[Item]:
    rng = random.Random(SEED)
    used_codes: set[str] = set()
    items: list[Item] = []
    for category in CATEGORIES:
        names = [
            template.format(*combo)
            for template in category.templates
            for combo in product(*category.options)
        ]
        for number, name in enumerate(sorted(rng.sample(names, PRODUCTS_PER_SECTION)), start=1):
            supplier_code = f"P{rng.randrange(10000, 90000)}"
            while supplier_code in used_codes:
                supplier_code = f"P{rng.randrange(10000, 90000)}"
            used_codes.add(supplier_code)
            in_dollars = rng.random() < category.dollars
            kind = rng.random()
            offer = rng.choice(QUANTITY_OFFERS)
            items.append(Item(
                section=category.section,
                internal_code=f"{category.prefix}-{number:04d}" if rng.random() < 0.62 else "",
                supplier_code=supplier_code,
                description=name,
                brand=rng.choice(BRANDS),
                unit=category.unit,
                price=round(rng.uniform(*category.price_range), 2),
                currency="u$s" if in_dollars else "$",
                vat="10,5%" if category.prefix == "AU" and rng.random() < 0.2 else "21%",
                discount=f"{rng.choice((5, 10, 15))}%" if kind < 0.22 else "",
                quantity_discount=f"{offer[0]}% x {offer[1]} UN" if 0.22 <= kind < 0.48 else "",
            ))
    return items


def _week_two(items: list[Item]) -> list[Item]:
    """The next week, simulated: drift, a few arrivals and departures, one tripled price."""
    rng = random.Random(SEED + 2)
    dropped = set(rng.sample(range(len(items)), DROPPED_PRODUCTS))
    result = []
    for index, item in enumerate(items):
        if index in dropped:
            continue
        roll = rng.random()
        if roll < 0.35:
            factor = 1 + rng.uniform(0.02, 0.09)
        elif roll < 0.45:
            factor = 1 - rng.uniform(0.01, 0.05)
        else:
            factor = 1.0
        result.append(replace(item, price=round(item.price * factor, 2)))
    anomaly = rng.choice([i for i, item in enumerate(result) if item.currency == "$"])
    result[anomaly] = replace(result[anomaly], price=round(result[anomaly].price * 3, 2))
    for number in range(NEW_PRODUCTS):
        result.append(Item(
            section=CATEGORIES[number].section, internal_code="", supplier_code=f"P{90000 + number * 7}",
            description=f"Producto nuevo línea 2026 {number + 1}", brand=rng.choice(BRANDS), unit="UN",
            price=round(rng.uniform(2500, 30000), 2), currency="$", vat="21%",
            discount="", quantity_discount="",
        ))
    return sorted(result, key=lambda item: SECTION_ORDER[item.section])  # stable within a section


def _cells(item: Item) -> list[object]:
    return [
        item.internal_code or None, item.supplier_code, item.description, item.brand, item.unit,
        item.price, item.currency, item.vat, item.discount or None, item.quantity_discount or None,
    ]


def _deterministic_zip(raw: bytes) -> bytes:
    """Rewrite the archive with fixed entry timestamps (openpyxl stamps the current time)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(out, "w") as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            data = source.read(name)
            if name == "docProps/core.xml":  # openpyxl overwrites `modified` with the clock on save
                data = _MODIFIED.sub(rf"\g<1>{_FIXED_STAMP}\g<2>", data.decode("utf-8")).encode("utf-8")
            target.writestr(info, data)
    return out.getvalue()


def render_week(week: int) -> bytes:
    """The XLSX bytes of one week's list (1 or 2)."""
    if week not in (1, 2):
        raise ValueError("week must be 1 or 2")
    items = _build_catalog()
    swap = week == 2
    if swap:
        items = _week_two(items)
    header = list(HEADER)
    if swap:  # week 2 swaps two columns: same names, different order
        header[1], header[2] = header[2], header[1]
    workbook = Workbook()
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    workbook.properties.creator = "Pricor sample generator"
    workbook.properties.lastModifiedBy = "Pricor sample generator"
    sheet = workbook.active
    sheet.title = "Lista de precios"
    prefix = "SIMULADA - " if swap else ""
    sheet.append([f"{prefix}DISTRIBUIDORA EJEMPLO S.A. - LISTA DE PRECIOS"])
    sheet.append([f"Semana {week}{' SIMULADA' if swap else ''} - datos ficticios generados para demostrar Pricor"])
    sheet.append([])
    sheet.append([])
    sheet.append(header)
    for cell in sheet[HEADER_ROW]:
        cell.font = Font(bold=True)
    section = None
    for item in items:
        if item.section != section:
            section = item.section
            sheet.append([f"*** {section} ***"])
        cells = _cells(item)
        if swap:
            cells[1], cells[2] = cells[2], cells[1]
        sheet.append(cells)
    for column, width in zip("ABCDEFGHIJ", (11, 11, 40, 10, 8, 16, 9, 7, 7, 14), strict=True):
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _deterministic_zip(buffer.getvalue())


def write_all(directory: Path = SAMPLES_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for sample in SAMPLES:
        path = directory / sample.file_name
        path.write_bytes(render_week(sample.week))
        paths.append(path)
    return paths


if __name__ == "__main__":
    for written in write_all():
        print(f"wrote {written} ({written.stat().st_size} bytes)")
