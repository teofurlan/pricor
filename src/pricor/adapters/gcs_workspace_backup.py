"""`WorkspaceBackup` adapter that saves and restores workspace SQLite files from Google Cloud Storage."""

from contextlib import closing
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from pricor.ports.workspace_backup import WorkspaceBackup

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "workspaces/"


def _validate_sqlite_file(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("PRAGMA quick_check").fetchone()
    if not row or row[0] != "ok":
        raise sqlite3.DatabaseError("restored SQLite file failed quick_check")


class GcsWorkspaceBackup(WorkspaceBackup):
    """Backs up workspaces to a Google Cloud Storage bucket so they survive instance restarts."""

    def __init__(
        self,
        bucket_name: str,
        client: Any | None = None,
        prefix: str = DEFAULT_PREFIX,
    ) -> None:
        if not bucket_name.strip():
            raise ValueError("bucket_name must not be empty")
        self._bucket_name = bucket_name.strip()
        self._prefix = prefix
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import storage  # lazy import
            self._client = storage.Client()
        return self._client

    def _blob_name(self, key: str) -> str:
        return f"{self._prefix}{key}.sqlite"

    def save(self, key: str, source: Path) -> None:
        client = self._get_client()
        bucket = client.bucket(self._bucket_name)
        blob = bucket.blob(self._blob_name(key))
        blob.upload_from_filename(str(source))

    def restore(self, key: str, target: Path) -> bool:
        client = self._get_client()
        bucket = client.bucket(self._bucket_name)
        blob = bucket.blob(self._blob_name(key))
        if not blob.exists():
            return False

        target.parent.mkdir(parents=True, exist_ok=True)
        # Download to a temporary file in the same directory, then rename atomically
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as tmp:
            tmp_path = Path(tmp.name)

        try:
            blob.download_to_filename(str(tmp_path))
            _validate_sqlite_file(tmp_path)
            os.replace(tmp_path, target)
            return True
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
