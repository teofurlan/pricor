"""Snapshot storage: save downloaded bytes, hash them, log every attempt.

Downloaded content is treated as untrusted bytes: it is written to disk and
hashed, never opened, parsed or executed.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

from tools.corpus.manifest import Source

SNAPSHOT_LOG = "snapshots.jsonl"


class FetchError(Exception):
    """A download failed; carries the HTTP status when one was received."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


@dataclass(frozen=True)
class FetchResult:
    status: int
    content: bytes
    content_type: str | None


Fetcher = Callable[[str], FetchResult]


@dataclass(frozen=True)
class SnapshotOutcome:
    source_id: str
    status: str  # "stored" | "unchanged" | "failed"
    path: Path | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    http_status: int | None = None
    error: str | None = None


def take_snapshot(
    source: Source, raw_root: Path, fetch: Fetcher, today: date
) -> SnapshotOutcome:
    """Fetch the source once and record the result; never raises on fetch errors."""
    source_dir = raw_root / source.id
    day = today.isoformat()
    base = {"date": day, "url": source.file_url}

    try:
        result = fetch(source.file_url)
    except FetchError as exc:
        return _record_failure(source_dir, base, source.id, str(exc), exc.http_status)
    except Exception as exc:  # noqa: BLE001 - one source must never abort the others
        return _record_failure(source_dir, base, source.id, f"{type(exc).__name__}: {exc}", None)

    sha256 = hashlib.sha256(result.content).hexdigest()
    size = len(result.content)
    meta = {
        **base,
        "sha256": sha256,
        "size_bytes": size,
        "content_type": result.content_type,
        "http_status": result.status,
        "error": None,
    }

    newest = _newest_snapshot(source_dir)
    if newest is not None and newest["sha256"] == sha256:
        _append(source_dir, {**meta, "outcome": "unchanged", "file": newest["file"]})
        return SnapshotOutcome(
            source.id,
            "unchanged",
            path=source_dir / newest["file"],
            sha256=sha256,
            size_bytes=size,
            content_type=result.content_type,
            http_status=result.status,
        )

    target = _unique_target(source_dir / day / _filename(source), sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.content)
    relative = target.relative_to(source_dir).as_posix()
    _append(source_dir, {**meta, "outcome": "stored", "file": relative})
    return SnapshotOutcome(
        source.id,
        "stored",
        path=target,
        sha256=sha256,
        size_bytes=size,
        content_type=result.content_type,
        http_status=result.status,
    )


def _record_failure(
    source_dir: Path, base: dict, source_id: str, error: str, http_status: int | None
) -> SnapshotOutcome:
    _append(
        source_dir,
        {
            **base,
            "sha256": None,
            "size_bytes": None,
            "content_type": None,
            "http_status": http_status,
            "outcome": "failed",
            "file": None,
            "error": error,
        },
    )
    return SnapshotOutcome(source_id, "failed", http_status=http_status, error=error)


def _filename(source: Source) -> str:
    """Decoded last URL path segment, reduced to a safe single path component."""
    name = unquote(urlparse(source.file_url).path.rsplit("/", 1)[-1])
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .")
    if not name or name.startswith("."):
        return f"{source.id}.{source.format}"
    return name


def _unique_target(target: Path, sha256: str) -> Path:
    """Never overwrite an earlier file from the same day with different content."""
    if not target.exists():
        return target
    return target.with_name(f"{target.stem}-{sha256[:8]}{target.suffix}")


def _newest_snapshot(source_dir: Path) -> dict | None:
    """Last logged attempt that actually produced content (skips failures)."""
    log = source_dir / SNAPSHOT_LOG
    if not log.exists():
        return None
    newest = None
    for line in log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("sha256") and record.get("file"):
            newest = record
    return newest


def _append(source_dir: Path, record: dict) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    with (source_dir / SNAPSHOT_LOG).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
