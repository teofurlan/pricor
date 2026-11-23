"""Persistent mapping between verified Google accounts and private workspaces."""

import contextlib
import hashlib
import logging
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pricor.ports.workspace_backup import WorkspaceBackup

logger = logging.getLogger(__name__)

ACCOUNT_BACKUP_KEY = "_accounts"


@dataclass(frozen=True)
class LinkedAccount:
    """A Google account linked to a private workspace."""

    sub: str
    email: str
    token: str
    workspace_key: str


def _workspace_key(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class WorkspaceAccountStore:
    """Stores Google-to-workspace links in `_accounts.sqlite` and syncs them via `WorkspaceBackup`."""

    def __init__(self, directory: Path, backup: WorkspaceBackup) -> None:
        self._directory = Path(directory)
        self._path = self._directory / "_accounts.sqlite"
        self._backup = backup
        self._lock = threading.Lock()
        self._initialized = False

    def _restore(self) -> None:
        try:
            restored = self._backup.restore(ACCOUNT_BACKUP_KEY, self._path)
        except Exception as error:
            logger.warning("account store restore failed (%s)", type(error).__name__)
            restored = False
        if not restored:
            self._path.unlink(missing_ok=True)

    def _ensure_ready(self) -> None:
        if self._initialized and self._path.is_file():
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        if not self._path.is_file():
            self._restore()
        with contextlib.closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_accounts (
                    google_sub TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    token TEXT NOT NULL,
                    workspace_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workspace_accounts_key ON workspace_accounts(workspace_key)"
            )
        self._initialized = True

    def _backup_quietly(self) -> None:
        try:
            with tempfile.TemporaryDirectory(dir=self._directory) as scratch:
                copy = Path(scratch) / "copy.sqlite"
                with (
                    contextlib.closing(sqlite3.connect(self._path)) as source,
                    contextlib.closing(sqlite3.connect(copy)) as target,
                ):
                    source.backup(target)
                self._backup.save(ACCOUNT_BACKUP_KEY, copy)
        except Exception as error:
            logger.warning(
                "account store backup failed (%s); the change is kept on this server only",
                type(error).__name__,
            )

    def get_by_sub(self, sub: str) -> LinkedAccount | None:
        with self._lock:
            self._ensure_ready()
            with contextlib.closing(sqlite3.connect(self._path)) as conn:
                row = conn.execute(
                    "SELECT google_sub, email, token, workspace_key FROM workspace_accounts WHERE google_sub = ?",
                    (sub,),
                ).fetchone()
        if row is None:
            return None
        return LinkedAccount(sub=row[0], email=row[1], token=row[2], workspace_key=row[3])

    def get_by_workspace_key(self, key: str) -> LinkedAccount | None:
        with self._lock:
            self._ensure_ready()
            with contextlib.closing(sqlite3.connect(self._path)) as conn:
                row = conn.execute(
                    "SELECT google_sub, email, token, workspace_key FROM workspace_accounts WHERE workspace_key = ?",
                    (key,),
                ).fetchone()
        if row is None:
            return None
        return LinkedAccount(sub=row[0], email=row[1], token=row[2], workspace_key=row[3])

    def link(self, sub: str, email: str, token: str) -> LinkedAccount:
        key = _workspace_key(token)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._ensure_ready()
            with contextlib.closing(sqlite3.connect(self._path)) as conn, conn:
                conn.execute(
                    "DELETE FROM workspace_accounts WHERE workspace_key = ? AND google_sub != ?",
                    (key, sub),
                )
                conn.execute(
                    """
                    INSERT INTO workspace_accounts (google_sub, email, token, workspace_key, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(google_sub) DO UPDATE SET
                        email = excluded.email,
                        token = excluded.token,
                        workspace_key = excluded.workspace_key,
                        updated_at = excluded.updated_at
                    """,
                    (sub, email, token, key, now),
                )
            self._backup_quietly()
        return LinkedAccount(sub=sub, email=email, token=token, workspace_key=key)

    def unlink_by_workspace_key(self, key: str) -> bool:
        with self._lock:
            self._ensure_ready()
            with contextlib.closing(sqlite3.connect(self._path)) as conn, conn:
                cursor = conn.execute(
                    "DELETE FROM workspace_accounts WHERE workspace_key = ?",
                    (key,),
                )
                deleted = cursor.rowcount > 0
            if deleted:
                self._backup_quietly()
        return deleted
