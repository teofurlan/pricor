import json
from pathlib import Path

import pytest

from pricor.domain.roles import ColumnRole
from tools.laya.labels import LabelError, load_labels
from tools.laya.split import HELD_OUT_DISTRIBUTORS, distributor_of, normalize_header, split_labels

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "tools" / "laya" / "labels.json"
SOURCES = ROOT / "data" / "sources.json"


def write(tmp_path, columns, sheets=None):
    sheets = sheets or [{"source_id": "a-1", "sheet": "S", "header_row": 0}]
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"sheets": sheets, "columns": columns}), encoding="utf-8")
    return path


def column(**overrides):
    base = {"source_id": "a-1", "sheet": "S", "index": 0, "header": "Cod", "role": "code"}
    return {**base, **overrides}


def test_labels_load_into_typed_entries(tmp_path):
    labels = load_labels(write(tmp_path, [column(note="n")]))

    (entry,) = labels.columns
    assert (entry.source_id, entry.sheet, entry.index, entry.header) == ("a-1", "S", 0, "Cod")
    assert entry.role is ColumnRole.CODE and entry.note == "n"
    assert labels.header_row("a-1", "S") == 0


@pytest.mark.parametrize(
    "bad",
    [
        column(role="price"),  # outside the closed set
        column(index=-1),
        column(header=5),
        column(sheet="Other"),  # no sheet spec
    ],
)
def test_a_bad_entry_is_refused(tmp_path, bad):
    with pytest.raises(LabelError):
        load_labels(write(tmp_path, [bad]))


def test_a_duplicated_column_is_refused(tmp_path):
    with pytest.raises(LabelError):
        load_labels(write(tmp_path, [column(), column()]))


def test_a_header_less_sheet_has_a_null_header_row(tmp_path):
    sheets = [{"source_id": "a-1", "sheet": "S", "header_row": None}]

    labels = load_labels(write(tmp_path, [column(header="")], sheets))

    assert labels.header_row("a-1", "S") is None


# -- the committed reference labels --


def test_the_committed_labels_are_valid_and_cover_known_sources():
    labels = load_labels(LABELS)
    known = {item["id"] for item in json.loads(SOURCES.read_text(encoding="utf-8"))}

    assert labels.columns
    assert {entry.source_id for entry in labels.columns} <= known
    assert "dipel-lista-000" not in {entry.source_id for entry in labels.columns}  # encrypted
    assert not any("simulated" in entry.source_id for entry in labels.columns)


def test_the_committed_labels_hold_headers_and_notes_only():
    raw = json.loads(LABELS.read_text(encoding="utf-8"))

    assert {key for entry in raw["columns"] for key in entry} <= {
        "source_id",
        "sheet",
        "index",
        "header",
        "role",
        "note",
    }


# -- split by distributor --


def test_distributors_group_the_files_of_one_supplier():
    assert distributor_of("dipel-lista-pagina-web") == distributor_of("dipel-haga-su-pedido") == "dipel"
    assert distributor_of("distrilap-libreria") == distributor_of("distrilap-computacion")
    assert distributor_of("electricidad-emilio") != distributor_of("distribucion-masiva-ferreteria")
    with pytest.raises(KeyError):
        distributor_of("unknown-supplier")


def test_dipel_and_distrilap_are_held_out_whole():
    assert HELD_OUT_DISTRIBUTORS == {"dipel", "distrilap"}
    split = split_labels(load_labels(LABELS))

    held = {distributor_of(entry.source_id) for entry in split.held_out.columns}
    train = {distributor_of(entry.source_id) for entry in split.train.columns}
    assert held == {"dipel", "distrilap"}
    assert train.isdisjoint(held)
    total = len(split.train.columns) + len(split.dropped) + len(split.held_out.columns)
    assert total == len(load_labels(LABELS).columns)


def test_every_training_column_with_a_held_out_header_is_dropped_from_the_training_pool():
    split = split_labels(load_labels(LABELS))

    banned = {normalize_header(entry.header) for entry in split.held_out.columns} - {""}
    assert "codigo" in banned and "descripcion" in banned
    assert not {normalize_header(entry.header) for entry in split.train.columns} & banned
    assert split.dropped, "the corpus has training columns that share a header with held-out ones"
    assert all(normalize_header(entry.header) in banned for entry in split.dropped)


def test_headers_normalize_without_accents_case_or_punctuation():
    assert normalize_header("Código  de Barras") == "codigodebarras"
    assert normalize_header("COD_PROV") == normalize_header("cod.prov") == "codprov"
    assert normalize_header("") == ""
