import hashlib
import json
from datetime import date

from tools.corpus.manifest import Source
from tools.corpus.snapshot import FetchError, FetchResult, take_snapshot

TODAY = date(2026, 10, 13)

SOURCE = Source(
    id="acme",
    name="Acme",
    page_url="https://acme.example/listas",
    file_url="https://acme.example/files/Lista%20Mayo.xlsx",
    format="xlsx",
    notes="",
)


def fetcher_returning(content, content_type="application/octet-stream", status=200):
    calls = []

    def fetch(url):
        calls.append(url)
        return FetchResult(status=status, content=content, content_type=content_type)

    fetch.calls = calls
    return fetch


def read_records(root, source_id="acme"):
    path = root / source_id / "snapshots.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_stores_file_under_id_and_date_with_decoded_original_name(tmp_path):
    outcome = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), TODAY)

    expected = tmp_path / "acme" / "2026-10-13" / "Lista Mayo.xlsx"
    assert outcome.status == "stored"
    assert outcome.path == expected
    assert expected.read_bytes() == b"abc"


def test_fetches_only_the_file_url_once(tmp_path):
    fetch = fetcher_returning(b"abc")

    take_snapshot(SOURCE, tmp_path, fetch, TODAY)

    assert fetch.calls == [SOURCE.file_url]


def test_record_has_hash_size_type_and_status(tmp_path):
    take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc", "text/csv"), TODAY)

    [record] = read_records(tmp_path)
    assert record == {
        "date": "2026-10-13",
        "url": SOURCE.file_url,
        "sha256": hashlib.sha256(b"abc").hexdigest(),
        "size_bytes": 3,
        "content_type": "text/csv",
        "http_status": 200,
        "outcome": "stored",
        "file": "2026-10-13/Lista Mayo.xlsx",
        "error": None,
    }


def test_identical_content_is_recorded_as_unchanged_without_new_file(tmp_path):
    take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), date(2026, 10, 13))

    outcome = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), date(2026, 10, 20))

    assert outcome.status == "unchanged"
    assert not (tmp_path / "acme" / "2026-10-20").exists()
    records = read_records(tmp_path)
    assert [r["outcome"] for r in records] == ["stored", "unchanged"]
    assert records[1]["sha256"] == records[0]["sha256"]
    assert records[1]["file"] == records[0]["file"]


def test_changed_content_is_stored_as_new_snapshot(tmp_path):
    take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), date(2026, 10, 13))

    outcome = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abcd"), date(2026, 10, 20))

    assert outcome.status == "stored"
    stored = tmp_path / "acme" / "2026-10-20" / "Lista Mayo.xlsx"
    assert stored.read_bytes() == b"abcd"


def test_same_day_change_does_not_overwrite_earlier_file(tmp_path):
    first = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), TODAY)

    second = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"xyz"), TODAY)

    assert second.status == "stored"
    assert second.path != first.path
    assert first.path.read_bytes() == b"abc"
    assert second.path.read_bytes() == b"xyz"


def test_unchanged_is_judged_against_newest_snapshot_only(tmp_path):
    take_snapshot(SOURCE, tmp_path, fetcher_returning(b"v1"), date(2026, 10, 13))
    take_snapshot(SOURCE, tmp_path, fetcher_returning(b"v2"), date(2026, 10, 20))

    outcome = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"v1"), date(2026, 10, 27))

    assert outcome.status == "stored"


def test_fetch_failure_is_reported_not_raised_and_stores_nothing(tmp_path):
    def failing(url):
        raise FetchError("HTTP 404", http_status=404)

    outcome = take_snapshot(SOURCE, tmp_path, failing, TODAY)

    assert outcome.status == "failed"
    assert "404" in outcome.error
    assert not (tmp_path / "acme" / "2026-10-13").exists()
    [record] = read_records(tmp_path)
    assert record["outcome"] == "failed"
    assert record["http_status"] == 404
    assert record["sha256"] is None


def test_failed_attempt_does_not_break_unchanged_detection(tmp_path):
    take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), date(2026, 10, 13))

    def failing(url):
        raise FetchError("timeout")

    take_snapshot(SOURCE, tmp_path, failing, date(2026, 10, 20))

    outcome = take_snapshot(SOURCE, tmp_path, fetcher_returning(b"abc"), date(2026, 10, 27))
    assert outcome.status == "unchanged"


def test_filename_falls_back_to_id_and_format_when_url_has_no_name(tmp_path):
    source = Source(
        id="acme",
        name="Acme",
        page_url="https://acme.example/",
        file_url="https://acme.example/download/",
        format="csv",
        notes="",
    )

    outcome = take_snapshot(source, tmp_path, fetcher_returning(b"a,b"), TODAY)

    assert outcome.path.name == "acme.csv"


def test_hostile_filename_cannot_escape_the_snapshot_directory(tmp_path):
    source = Source(
        id="acme",
        name="Acme",
        page_url="https://acme.example/",
        file_url="https://acme.example/..%2F..%2Fevil.xlsx",
        format="xlsx",
        notes="",
    )

    outcome = take_snapshot(source, tmp_path, fetcher_returning(b"x"), TODAY)

    assert outcome.path.parent == tmp_path / "acme" / "2026-10-13"
