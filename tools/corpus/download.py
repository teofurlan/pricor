"""Download public distributor price lists listed in ``data/sources.json``.

Usage (from the repository root)::

    uv run python -m tools.corpus.download [--only ID ...] [--manifest PATH] [--out DIR]

One request per file; no crawling. Files land in
``data/raw/<id>/<YYYY-MM-DD>/`` (gitignored) and every attempt is appended to
``data/raw/<id>/snapshots.jsonl``. Downloaded bytes are only saved, never opened.
"""

import argparse
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from tools.corpus.manifest import load_manifest
from tools.corpus.snapshot import FetchError, FetchResult, Fetcher, SnapshotOutcome, take_snapshot

USER_AGENT = "pricor-corpus-downloader/0.1 (+research; one request per public price list)"
TIMEOUT_SECONDS = 60
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "data" / "sources.json"
DEFAULT_OUT = REPO_ROOT / "data" / "raw"


def urllib_fetcher(url: str) -> FetchResult:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return FetchResult(
                status=response.status,
                content=response.read(),
                content_type=response.headers.get("Content-Type"),
            )
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} {exc.reason}", http_status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc


def run(
    manifest: Path,
    raw_root: Path,
    fetch: Fetcher,
    today: date,
    only: Iterable[str] | None = None,
) -> list[SnapshotOutcome]:
    selected = set(only) if only else None
    outcomes = []
    for source in load_manifest(manifest):
        if selected is not None and source.id not in selected:
            continue
        outcomes.append(take_snapshot(source, raw_root, fetch, today))
    return outcomes


def format_summary(outcomes: list[SnapshotOutcome]) -> str:
    lines = []
    for outcome in outcomes:
        if outcome.status == "failed":
            lines.append(f"{outcome.source_id}: FAILED - {outcome.error}")
        else:
            lines.append(
                f"{outcome.source_id}: {outcome.status} - {outcome.path.name} "
                f"({outcome.size_bytes} bytes, sha256 {outcome.sha256})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", nargs="+", metavar="ID", help="restrict to these source ids")
    args = parser.parse_args(argv)

    outcomes = run(args.manifest, args.out, urllib_fetcher, date.today(), args.only)
    print(format_summary(outcomes))
    return 1 if any(o.status == "failed" for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
