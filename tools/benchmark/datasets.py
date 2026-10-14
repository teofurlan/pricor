"""The two evaluation sets, built from the same labels and raw files the training used.

* The **validation set** is the header-disjoint slice carved from the training distributors
  (real resamples and synthetic columns). It is for calibration only.
* The **held-out test set** is every labeled column of Dipel and DistriLap, profiled whole-sheet
  the way the runtime does. Nothing is tuned on it.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.domain.profile import ColumnProfile, SheetProfile, profile_sheet
from pricor.ports.spreadsheet import SpreadsheetReader
from tools.laya.build import build_datasets
from tools.laya.dataset import Example, find_snapshot_file
from tools.laya.labels import load_labels
from tools.laya.split import split_labels

CHUNK_SIZE = 8


@dataclass(frozen=True)
class SheetCase:
    """One held-out sheet: its profile and the reference role of each labeled column index."""

    source_id: str
    sheet: str
    profile: SheetProfile
    expected: dict[int, str]

    def expected_in_order(self) -> list[tuple[int, str]]:
        return sorted(self.expected.items())


def chunk_columns(
    columns: Sequence[ColumnProfile], size: int = CHUNK_SIZE, seed: int = 0
) -> list[tuple[SheetProfile, list[int]]]:
    """Group loose columns into pseudo-sheets of `size`, in a seeded shuffled order.

    Each pseudo-sheet re-numbers its columns from 0 and comes with the original positions, so
    answers can be put back in order. Validation columns come from many different sheets; a
    sheet-level classifier (Gemma) needs some sheet to read them from.
    """
    order = list(range(len(columns)))
    random.Random(seed).shuffle(order)
    chunks = []
    for start in range(0, len(order), size):
        positions = order[start : start + size]
        renumbered = tuple(replace(columns[p], index=i) for i, p in enumerate(positions))
        sheet = SheetProfile(0, 1.0, False, (), (), renumbered)
        chunks.append((sheet, positions))
    return chunks


def validation_examples(raw_root: Path, labels_path: Path, seed: int = 0) -> list[Example]:
    """The validation examples exactly as the training run carved them (same seed, same data)."""
    return list(build_datasets(raw_root, labels_path, seed).validation)


def held_out_cases(
    raw_root: Path, labels_path: Path, reader: SpreadsheetReader | None = None
) -> list[SheetCase]:
    """Every held-out sheet with its whole-sheet profile and reference roles."""
    reader = reader or FileSpreadsheetReader()
    labels = load_labels(labels_path)
    held = split_labels(labels).held_out
    grouped: dict[tuple[str, str], dict[int, str]] = {}
    for column in held.columns:
        grouped.setdefault((column.source_id, column.sheet), {})[column.index] = column.role.value
    cases = []
    for (source_id, sheet), expected in grouped.items():
        rows = reader.read_sheet(find_snapshot_file(raw_root, source_id), sheet).rows
        profile = profile_sheet(rows, labels.header_row(source_id, sheet))
        cases.append(SheetCase(source_id, sheet, profile, expected))
    return cases
