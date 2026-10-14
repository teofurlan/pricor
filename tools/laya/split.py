"""Split the reference labels by distributor, never by column.

Two whole distributors are held out for testing: Dipel (has PRECIO LISTA and PRECIO VENTA) and
DistriLap (its lists have no header row). Training sees neither their columns nor any column
whose exact normalized header equals a held-out header, and the synthetic generator avoids
those headers too (see `synth`). The empty header is exempt: "no header" is a kind of column,
not a header text, and the synthetic header-less examples are how the model learns it.
"""

import unicodedata
from dataclasses import dataclass

from .labels import LabeledColumn, LabelSet

# The first token of a source id names its distributor, except where the id says otherwise.
_DISTRIBUTORS = {
    "dipel": "dipel",
    "distrilap": "distrilap",
    "electricidad-emilio": "electricidad-emilio",
    "distribucion-masiva-ferreteria": "distribucion-masiva",
    "bulonera-camba-completa": "bulonera-camba",
    "megamayorista-libreria": "megamayorista",
}
HELD_OUT_DISTRIBUTORS = frozenset({"dipel", "distrilap"})


def distributor_of(source_id: str) -> str:
    """The distributor a source belongs to; raises `KeyError` for an unknown source."""
    for prefix, distributor in _DISTRIBUTORS.items():
        if source_id == prefix or source_id.startswith(prefix + "-"):
            return distributor
    raise KeyError(source_id)


def normalize_header(text: str) -> str:
    """Accents, case, spaces and punctuation removed: the key for 'same header' comparisons."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if c.isalnum() and unicodedata.category(c) != "Mn")


@dataclass(frozen=True)
class Split:
    train: LabelSet
    held_out: LabelSet
    dropped: tuple[LabeledColumn, ...]  # training-distributor columns sharing a held-out header

    @property
    def banned_headers(self) -> frozenset[str]:
        return held_out_headers(self.held_out)


def held_out_headers(held_out: LabelSet) -> frozenset[str]:
    """Normalized headers no training or synthetic example may use (empty header excluded)."""
    return frozenset(normalize_header(c.header) for c in held_out.columns) - {""}


def split_labels(labels: LabelSet) -> Split:
    held = tuple(c for c in labels.columns if distributor_of(c.source_id) in HELD_OUT_DISTRIBUTORS)
    rest = tuple(c for c in labels.columns if distributor_of(c.source_id) not in HELD_OUT_DISTRIBUTORS)
    banned = held_out_headers(labels.only(held))
    kept = tuple(c for c in rest if normalize_header(c.header) not in banned)
    dropped = tuple(c for c in rest if normalize_header(c.header) in banned)
    return Split(labels.only(kept), labels.only(held), dropped)
