import json
from collections import Counter
from pathlib import Path

import pytest

from pricor.domain.roles import ColumnRole
from tools.laya.dataset import (
    Example,
    LeakageError,
    assert_no_leakage,
    examples_from_sheet,
    find_snapshot_file,
    inference_examples,
    jsonl_row,
    label_counts,
    split_validation,
    synthetic_examples,
    write_jsonl,
)
from tools.laya.labels import LabeledColumn
from tools.laya.split import normalize_header

HEADER = ("Codigo", "Detalle", "Costo")


def sheet_rows(n=120, header=HEADER):
    rows = [header] if header else []
    rows += [(f"A{i:04d}", f"Producto {i}", f"{10 + i * 1.5:.2f}".replace(".", ",")) for i in range(n)]
    return tuple(rows)


def labeled(*roles, header=HEADER):
    return tuple(
        LabeledColumn("acme-1", "S", i, header[i] if header else "", role)
        for i, role in enumerate(roles)
    )


ROLES = (ColumnRole.CODE, ColumnRole.DESCRIPTION, ColumnRole.COST_PRICE)


# -- real columns, resampled --


def test_every_real_column_gives_one_example_per_resample_with_its_label():
    examples = examples_from_sheet(sheet_rows(), 0, labeled(*ROLES), resamples=4, seed=1)

    assert len(examples) == 12
    assert Counter(e.role for e in examples) == {r: 4 for r in ROLES}
    assert {e.origin for e in examples} == {"real"} and {e.source for e in examples} == {"acme-1"}
    assert all(e.state.startswith(f"Column header: {e.header}\n") for e in examples)


def test_resampling_changes_the_sample_values_but_is_deterministic():
    first = examples_from_sheet(sheet_rows(), 0, labeled(*ROLES), resamples=5, seed=1)
    again = examples_from_sheet(sheet_rows(), 0, labeled(*ROLES), resamples=5, seed=1)
    other = examples_from_sheet(sheet_rows(), 0, labeled(*ROLES), resamples=5, seed=2)

    assert first == again
    assert first != other
    code_states = {e.state for e in first if e.role is ColumnRole.CODE}
    assert len(code_states) > 1


def test_a_header_less_sheet_gives_header_less_examples():
    examples = examples_from_sheet(sheet_rows(header=None), None, labeled(*ROLES, header=None), 2, 1)

    assert len(examples) == 6
    assert all("Column header: (no header)" in e.state for e in examples)


def test_a_header_that_differs_from_the_label_is_refused_because_the_file_drifted():
    wrong = (LabeledColumn("acme-1", "S", 0, "Referencia", ColumnRole.CODE),)

    with pytest.raises(ValueError, match="Referencia"):
        examples_from_sheet(sheet_rows(), 0, wrong, resamples=1, seed=1)


def test_rows_that_are_not_data_do_not_reach_the_samples():
    rows = (*sheet_rows(40), ("TOTAL", None, "9.999,00"), (None, None, None))

    examples = examples_from_sheet(rows, 0, labeled(*ROLES), resamples=6, seed=3)

    assert not any("TOTAL" in e.state for e in examples)


def test_inference_examples_use_the_whole_sheet_profile_once_per_column():
    examples = inference_examples(sheet_rows(), 0, labeled(*ROLES))

    assert [e.role for e in examples] == list(ROLES)
    assert examples[0].state.startswith("Column header: Codigo\nColumn type: code")


# -- synthetic --


def test_synthetic_examples_are_labeled_synthetic_and_avoid_banned_headers():
    banned = frozenset({"codigo", "descripcion"})

    examples = synthetic_examples(100, seed=4, banned=banned)

    assert len(examples) == 100
    assert {e.origin for e in examples} == {"synthetic"} and {e.source for e in examples} == {"synthetic"}
    assert not {normalize_header(e.header) for e in examples} & banned
    assert all(e.state.startswith("Column header: ") for e in examples)


def test_synthetic_header_less_examples_say_no_header():
    examples = synthetic_examples(200, seed=4, banned=frozenset())

    assert any(e.header == "" and "Column header: (no header)" in e.state for e in examples)


# -- leakage guard --


def test_a_banned_header_in_training_examples_is_refused():
    leaked = [Example("s", ColumnRole.CODE, "real", "electricidad-emilio", "CÓDIGO")]

    with pytest.raises(LeakageError, match="codigo"):
        assert_no_leakage(leaked, frozenset({"codigo"}))


def test_a_held_out_distributor_in_training_examples_is_refused():
    leaked = [Example("s", ColumnRole.CODE, "real", "dipel-lista-pagina-web", "Whatever")]

    with pytest.raises(LeakageError, match="dipel"):
        assert_no_leakage(leaked, frozenset())


def test_clean_examples_and_header_less_ones_pass():
    clean = [
        Example("s", ColumnRole.CODE, "real", "electricidad-emilio", "Referencia"),
        Example("s", ColumnRole.CODE, "synthetic", "synthetic", ""),
    ]

    assert_no_leakage(clean, frozenset({"codigo", ""}))  # the empty header is exempt


# -- validation split --


def pool():
    out = []
    for role in ColumnRole:
        for h in range(10):
            out += [Example(f"state-{role}-{h}-{r}", role, "synthetic", "synthetic", f"{role.value}{h}") for r in range(3)]
    return out


def test_validation_is_carved_by_header_so_no_header_is_in_both_sides():
    train, val = split_validation(pool(), fraction=0.2, seed=5)

    assert val and train
    assert not {normalize_header(e.header) for e in train} & {normalize_header(e.header) for e in val}
    assert len(train) + len(val) == len(pool())


def test_validation_covers_every_role_and_is_deterministic():
    train, val = split_validation(pool(), fraction=0.2, seed=5)

    assert {e.role for e in val} == set(ColumnRole)
    assert (train, val) == split_validation(pool(), fraction=0.2, seed=5)
    assert 0.1 < len(val) / len(pool()) < 0.35


# -- serialization --


def test_jsonl_rows_carry_state_question_and_gold_label():
    row = jsonl_row(Example("State text", ColumnRole.CODE, "real", "acme-1", "Cod"))

    assert row["state"] == "State text"
    assert row["expected"] == {"role": "code"}
    assert set(row["questions"]["role"]["criteria"]) == {r.value for r in ColumnRole}


def test_examples_are_written_as_one_json_object_per_line(tmp_path):
    path = tmp_path / "out.jsonl"

    write_jsonl(path, [Example("é\nx", ColumnRole.CODE, "real", "a", "h"), Example("y", ColumnRole.IGNORE, "real", "a", "h")])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["expected"]["role"] for line in lines] == ["code", "ignore"]
    assert json.loads(lines[0])["state"] == "é\nx"


def test_label_counts_cover_every_role_even_when_absent():
    counts = label_counts([Example("s", ColumnRole.CODE, "real", "a", "h")])

    assert counts["code"] == 1 and counts["barcode"] == 0 and len(counts) == len(ColumnRole)


# -- locating raw files --


def test_the_latest_dated_snapshot_file_is_found_and_simulated_ones_are_ignored(tmp_path):
    base = tmp_path / "acme-1"
    for folder, name in (("2026-10-13", "old.xlsx"), ("2026-10-20", "new.xlsx"), ("2026-10-13-simulated", "fake.xlsx")):
        (base / folder).mkdir(parents=True)
        (base / folder / name).write_bytes(b"x")

    assert find_snapshot_file(tmp_path, "acme-1") == base / "2026-10-20" / "new.xlsx"


def test_a_source_without_a_snapshot_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="acme-1"):
        find_snapshot_file(tmp_path, "acme-1")


RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


@pytest.mark.skipif(not RAW.is_dir(), reason="needs the downloaded corpus in data/raw")
def test_the_real_corpus_builds_a_leak_free_training_set():
    from tools.laya.build import build_datasets
    from tools.laya.split import HELD_OUT_DISTRIBUTORS, distributor_of

    data = build_datasets(RAW, Path(__file__).resolve().parents[2] / "tools" / "laya" / "labels.json", seed=0)

    assert {distributor_of(e.source) for e in data.train if e.origin == "real"}.isdisjoint(HELD_OUT_DISTRIBUTORS)
    assert not {normalize_header(e.header) for e in (*data.train, *data.validation)} & data.banned_headers
    assert {e.source for e in data.held_out} and all(
        distributor_of(e.source) in HELD_OUT_DISTRIBUTORS for e in data.held_out
    )
    assert {e.role for e in data.train} == set(ColumnRole)
