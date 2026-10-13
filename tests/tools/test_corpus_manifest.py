import json

import pytest

from tools.corpus.manifest import ManifestError, Source, load_manifest


def write_manifest(tmp_path, entries):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def valid_entry(**overrides):
    entry = {
        "id": "acme",
        "name": "Acme Distribuidora",
        "page_url": "https://acme.example/listas",
        "file_url": "https://acme.example/lista.xlsx",
        "format": "xlsx",
        "notes": "public price list",
    }
    entry.update(overrides)
    return entry


def test_loads_valid_entries(tmp_path):
    path = write_manifest(tmp_path, [valid_entry()])

    sources = load_manifest(path)

    assert sources == [
        Source(
            id="acme",
            name="Acme Distribuidora",
            page_url="https://acme.example/listas",
            file_url="https://acme.example/lista.xlsx",
            format="xlsx",
            notes="public price list",
        )
    ]


def test_notes_are_optional_and_default_to_empty(tmp_path):
    entry = valid_entry()
    del entry["notes"]

    sources = load_manifest(write_manifest(tmp_path, [entry]))

    assert sources[0].notes == ""


@pytest.mark.parametrize("missing", ["id", "name", "page_url", "file_url", "format"])
def test_missing_required_key_is_rejected(tmp_path, missing):
    entry = valid_entry()
    del entry[missing]

    with pytest.raises(ManifestError, match=missing):
        load_manifest(write_manifest(tmp_path, [entry]))


def test_unsupported_format_is_rejected(tmp_path):
    with pytest.raises(ManifestError, match="format"):
        load_manifest(write_manifest(tmp_path, [valid_entry(format="pdf")]))


def test_duplicate_ids_are_rejected(tmp_path):
    entries = [valid_entry(), valid_entry(name="Other")]

    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(write_manifest(tmp_path, entries))


@pytest.mark.parametrize("bad_id", ["../evil", "Has Space", "UPPER", "a/b", ""])
def test_id_must_be_a_safe_slug(tmp_path, bad_id):
    with pytest.raises(ManifestError, match="id"):
        load_manifest(write_manifest(tmp_path, [valid_entry(id=bad_id)]))


@pytest.mark.parametrize(
    "bad_url", ["ftp://x.example/a.xlsx", "file:///etc/passwd", "lista.xlsx"]
)
def test_file_url_must_be_http_or_https(tmp_path, bad_url):
    with pytest.raises(ManifestError, match="file_url"):
        load_manifest(write_manifest(tmp_path, [valid_entry(file_url=bad_url)]))


def test_top_level_must_be_a_list(tmp_path):
    with pytest.raises(ManifestError, match="list"):
        load_manifest(write_manifest(tmp_path, {"id": "acme"}))
