import json
from datetime import date

from tools.corpus.download import run
from tools.corpus.snapshot import FetchError, FetchResult

TODAY = date(2026, 10, 13)


def write_manifest(tmp_path, ids):
    entries = [
        {
            "id": source_id,
            "name": source_id.title(),
            "page_url": f"https://{source_id}.example/",
            "file_url": f"https://{source_id}.example/lista.xlsx",
            "format": "xlsx",
            "notes": "",
        }
        for source_id in ids
    ]
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_one_failing_source_does_not_abort_the_others(tmp_path):
    manifest = write_manifest(tmp_path, ["alpha", "beta", "gamma"])

    def fetch(url):
        if "beta" in url:
            raise FetchError("HTTP 500", http_status=500)
        return FetchResult(status=200, content=url.encode(), content_type="x/y")

    outcomes = run(manifest, tmp_path / "raw", fetch, TODAY)

    assert [(o.source_id, o.status) for o in outcomes] == [
        ("alpha", "stored"),
        ("beta", "failed"),
        ("gamma", "stored"),
    ]


def test_unexpected_exception_from_fetcher_is_isolated_too(tmp_path):
    manifest = write_manifest(tmp_path, ["alpha", "beta"])

    def fetch(url):
        if "alpha" in url:
            raise RuntimeError("boom")
        return FetchResult(status=200, content=b"ok", content_type="x/y")

    outcomes = run(manifest, tmp_path / "raw", fetch, TODAY)

    assert [o.status for o in outcomes] == ["failed", "stored"]


def test_only_filter_restricts_to_selected_ids(tmp_path):
    manifest = write_manifest(tmp_path, ["alpha", "beta"])
    seen = []

    def fetch(url):
        seen.append(url)
        return FetchResult(status=200, content=b"ok", content_type="x/y")

    run(manifest, tmp_path / "raw", fetch, TODAY, only=["beta"])

    assert seen == ["https://beta.example/lista.xlsx"]
