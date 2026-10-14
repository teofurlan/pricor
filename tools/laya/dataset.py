"""Labeled examples for Laya: real columns (resampled), synthetic columns, validation carve-out.

Every example's state text goes through `pricor.adapters.laya_state`, the serializer the
runtime adapter uses, and every state is built from a *profile* of the column (the profiler is
what decides the apparent type and the samples at inference time), so training sees exactly the
shape of input the classifier will get.
"""

import json
import math
import random
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pricor.adapters.laya_state import QUESTION_ID, QUESTIONS, serialize_column, state_for_column
from pricor.domain.profile import ColumnProfile, RowClass, SheetProfile, profile_sheet
from pricor.domain.roles import ColumnRole

from .labels import LabeledColumn
from .split import HELD_OUT_DISTRIBUTORS, distributor_of, normalize_header
from .synth import generate_columns

MIN_SUBSET, MAX_SUBSET = 20, 200
_DATE_FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}")


class LeakageError(AssertionError):
    """Held-out material reached a training or validation pool."""


@dataclass(frozen=True)
class Example:
    state: str
    role: ColumnRole
    origin: str  # "real" or "synthetic"
    source: str  # a source id, or "synthetic"
    header: str  # the column header as written ("" when it has none)


# -- real columns ----------------------------------------------------------------


def _pad(row: Sequence[Any], width: int) -> tuple[Any, ...]:
    return (*row, *([None] * (width - len(row))))


def _check_headers(profile: SheetProfile, columns: Sequence[LabeledColumn]) -> None:
    for column in columns:
        if column.index >= len(profile.columns):
            raise ValueError(f"{column.source_id}/{column.sheet}: no column {column.index}")
        found = profile.columns[column.index].raw_header
        if found != column.header:
            raise ValueError(
                f"{column.source_id}/{column.sheet} column {column.index}: the labels say "
                f"{column.header!r} but the file has {found!r}; the file changed"
            )


def examples_from_sheet(
    rows: Sequence[Sequence[Any]],
    header_row: int | None,
    columns: Sequence[LabeledColumn],
    resamples: int,
    seed: int,
) -> list[Example]:
    """`resamples` examples per labeled column, each profiled from a different random row subset."""
    full = profile_sheet(rows, header_row)
    _check_headers(full, columns)
    width = len(full.columns)
    data = [rows[index] for index in full.indexes_of(RowClass.DATA)]
    head = [] if header_row is None else [_pad(rows[header_row], width)]
    first = columns[0]
    rng = random.Random(f"{seed}:{first.source_id}:{first.sheet}")
    examples = []
    for _ in range(resamples):
        size = min(len(data), rng.randint(MIN_SUBSET, MAX_SUBSET))
        subset = [_pad(row, width) for row in rng.sample(data, size)]
        profile = profile_sheet([*head, *subset], 0 if head else None)
        examples += [
            Example(state_for_column(profile.columns[c.index]), c.role, "real", c.source_id, c.header)
            for c in columns
        ]
    return examples


def inference_examples(
    rows: Sequence[Sequence[Any]], header_row: int | None, columns: Sequence[LabeledColumn]
) -> list[Example]:
    """One example per column from the whole-sheet profile, the way the runtime classifies."""
    profile = profile_sheet(rows, header_row)
    _check_headers(profile, columns)
    return [
        Example(state_for_column(profile.columns[c.index]), c.role, "real", c.source_id, c.header)
        for c in columns
    ]


# -- synthetic columns -----------------------------------------------------------


def _single_column_profile(header: str, values: Sequence[str]) -> ColumnProfile | None:
    rows = [*([(header,)] if header else []), *[(value or None,) for value in values]]
    profile = profile_sheet(rows, 0 if header else None)
    return profile.columns[0] if profile.columns else None


def synthetic_examples(count: int, seed: int, banned: frozenset[str]) -> list[Example]:
    examples = []
    for column in generate_columns(count, seed, banned):
        profile = _single_column_profile(column.header, column.values)
        state = (
            state_for_column(profile)
            if profile is not None
            else serialize_column(column.header, "empty", [])
        )
        examples.append(Example(state, column.role, "synthetic", "synthetic", column.header))
    return examples


# -- guards and splits -----------------------------------------------------------


def assert_no_leakage(examples: Sequence[Example], banned_headers: frozenset[str]) -> None:
    """Refuse examples from a held-out distributor or with a held-out normalized header.

    The empty header is exempt: it marks a header-less column, which is a kind of column and
    not a header text.
    """
    for example in examples:
        if example.source != "synthetic" and distributor_of(example.source) in HELD_OUT_DISTRIBUTORS:
            raise LeakageError(
                f"example from {example.source} ({distributor_of(example.source)}), a held-out distributor"
            )
        key = normalize_header(example.header)
        if key and key in banned_headers:
            raise LeakageError(f"example header {example.header!r} normalizes to held-out header {key!r}")


def split_validation(
    examples: Sequence[Example], fraction: float, seed: int
) -> tuple[list[Example], list[Example]]:
    """Carve a validation set whose headers never appear in the training side.

    Examples are grouped by normalized header (header-less ones stand alone), groups are
    shuffled with `seed`, and each role gets about `fraction` of its examples in validation.
    """
    groups: dict[str, list[Example]] = defaultdict(list)
    for index, example in enumerate(examples):
        key = normalize_header(example.header)
        groups[key if key else f"#{index}"].append(example)
    totals: dict[ColumnRole, int] = defaultdict(int)
    for example in examples:
        totals[example.role] += 1
    quota = {role: math.ceil(fraction * total) for role, total in totals.items()}
    taken: dict[ColumnRole, int] = defaultdict(int)

    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    validation_keys = set()
    for key in keys:
        roles = {example.role for example in groups[key]}
        if any(taken[role] < quota[role] for role in roles):
            validation_keys.add(key)
            for example in groups[key]:
                taken[example.role] += 1
    train, validation = [], []
    for key in sorted(groups):
        (validation if key in validation_keys else train).extend(groups[key])
    return train, validation


def label_counts(examples: Sequence[Example]) -> dict[str, int]:
    counts = {role.value: 0 for role in ColumnRole}
    for example in examples:
        counts[example.role.value] += 1
    return counts


# -- files -----------------------------------------------------------------------


def jsonl_row(example: Example) -> dict[str, Any]:
    return {"state": example.state, "questions": QUESTIONS, "expected": {QUESTION_ID: example.role.value}}


def write_jsonl(path: Path, examples: Sequence[Example]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for example in examples:
            handle.write(json.dumps(jsonl_row(example), ensure_ascii=False) + "\n")


def find_snapshot_file(raw_root: Path, source_id: str) -> Path:
    """The file of the latest dated real snapshot of a source (simulated folders are skipped)."""
    folders = sorted(
        folder
        for folder in (Path(raw_root) / source_id).glob("*")
        if folder.is_dir() and _DATE_FOLDER.fullmatch(folder.name)
    )
    for folder in reversed(folders):
        files = sorted(item for item in folder.iterdir() if item.is_file())
        if files:
            return files[0]
    raise FileNotFoundError(f"no downloaded snapshot for {source_id} under {raw_root}")
