"""Build the train, validation and held-out example sets from the raw corpus and the labels."""

from dataclasses import dataclass
from pathlib import Path

from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.ports.spreadsheet import SpreadsheetReader

from .dataset import (
    Example,
    assert_no_leakage,
    examples_from_sheet,
    find_snapshot_file,
    inference_examples,
    split_validation,
    synthetic_examples,
)
from .labels import LabeledColumn, LabelSet, load_labels
from .split import Split, split_labels

RESAMPLES = 12
SYNTHETIC_COUNT = 800
VALIDATION_FRACTION = 0.12


@dataclass(frozen=True)
class Datasets:
    train: tuple[Example, ...]
    validation: tuple[Example, ...]
    held_out: tuple[Example, ...]
    banned_headers: frozenset[str]
    dropped: tuple[LabeledColumn, ...]


def _by_sheet(labels: LabelSet) -> dict[tuple[str, str], list[LabeledColumn]]:
    grouped: dict[tuple[str, str], list[LabeledColumn]] = {}
    for column in labels.columns:
        grouped.setdefault((column.source_id, column.sheet), []).append(column)
    return grouped


def _rows(reader: SpreadsheetReader, raw_root: Path, source_id: str, sheet: str):
    return reader.read_sheet(find_snapshot_file(raw_root, source_id), sheet).rows


def _held_out(reader: SpreadsheetReader, raw_root: Path, labels: LabelSet, split: Split) -> list[Example]:
    examples: list[Example] = []
    for (source_id, sheet), columns in _by_sheet(split.held_out).items():
        examples += inference_examples(
            _rows(reader, raw_root, source_id, sheet), labels.header_row(source_id, sheet), columns
        )
    return examples


def build_held_out(
    raw_root: Path, labels_path: Path, reader: SpreadsheetReader | None = None
) -> list[Example]:
    """Only the held-out distributors' columns, profiled whole-sheet like the runtime does."""
    labels = load_labels(labels_path)
    return _held_out(reader or FileSpreadsheetReader(), raw_root, labels, split_labels(labels))


def build_datasets(
    raw_root: Path,
    labels_path: Path,
    seed: int,
    resamples: int = RESAMPLES,
    synthetic: int = SYNTHETIC_COUNT,
    validation_fraction: float = VALIDATION_FRACTION,
    reader: SpreadsheetReader | None = None,
) -> Datasets:
    """Real training columns (resampled) plus synthetic ones, minus a header-disjoint validation set.

    The held-out distributors contribute only the `held_out` examples, profiled whole-sheet
    the way the runtime classifies. Leakage is asserted before anything is returned.
    """
    reader = reader or FileSpreadsheetReader()
    labels = load_labels(labels_path)
    split: Split = split_labels(labels)
    held_out = _held_out(reader, raw_root, labels, split)

    real: list[Example] = []
    for (source_id, sheet), columns in _by_sheet(split.train).items():
        header_row = labels.header_row(source_id, sheet)
        real += examples_from_sheet(
            _rows(reader, raw_root, source_id, sheet), header_row, columns, resamples, seed
        )
    banned = split.banned_headers
    pool = [*real, *synthetic_examples(synthetic, seed, banned)]
    assert_no_leakage(pool, banned)
    train, validation = split_validation(pool, validation_fraction, seed)
    return Datasets(tuple(train), tuple(validation), tuple(held_out), banned, split.dropped)


__all__ = ["Datasets", "build_datasets", "build_held_out"]
