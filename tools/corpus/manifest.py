"""Manifest of public price-list sources (``data/sources.json``)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_FORMATS = frozenset({"xlsx", "xls", "xlsm", "csv"})
_REQUIRED_KEYS = ("id", "name", "page_url", "file_url", "format")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ManifestError(ValueError):
    """The manifest is malformed or contains an invalid entry."""


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    page_url: str
    file_url: str
    format: str
    notes: str


def load_manifest(path: Path) -> list[Source]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ManifestError("manifest must be a JSON list of source entries")

    sources: list[Source] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        source = _parse_entry(entry, index)
        if source.id in seen:
            raise ManifestError(f"duplicate id: {source.id!r}")
        seen.add(source.id)
        sources.append(source)
    return sources


def _parse_entry(entry: object, index: int) -> Source:
    if not isinstance(entry, dict):
        raise ManifestError(f"entry {index} must be an object")
    for key in _REQUIRED_KEYS:
        if key not in entry:
            raise ManifestError(f"entry {index} is missing required key {key!r}")

    source = Source(
        id=str(entry["id"]),
        name=str(entry["name"]),
        page_url=str(entry["page_url"]),
        file_url=str(entry["file_url"]),
        format=str(entry["format"]),
        notes=str(entry.get("notes", "")),
    )
    if not _SLUG.match(source.id):
        raise ManifestError(f"entry {index}: id {source.id!r} is not a lowercase slug")
    if source.format not in SUPPORTED_FORMATS:
        raise ManifestError(
            f"entry {source.id!r}: format {source.format!r} not in {sorted(SUPPORTED_FORMATS)}"
        )
    if not source.file_url.startswith(("http://", "https://")):
        raise ManifestError(f"entry {source.id!r}: file_url must be http(s)")
    return source
