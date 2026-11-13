"""Where private workspaces are copied so they survive a restart of the server."""

from pathlib import Path
from typing import Protocol


class WorkspaceBackup(Protocol):
    """Stores one SQLite file per workspace under an opaque key (never the visitor's token)."""

    def save(self, key: str, source: Path) -> None:
        """Replace the copy stored under `key` with the file at `source`."""

    def restore(self, key: str, target: Path) -> bool:
        """Write the copy stored under `key` to `target`; False when there is none."""


class NoWorkspaceBackup:
    """Keeps nothing: workspaces live only on the local disk."""

    def save(self, key: str, source: Path) -> None:
        return None

    def restore(self, key: str, target: Path) -> bool:
        return False
