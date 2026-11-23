from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import MagicMock

import pytest

from pricor.adapters.gcs_workspace_backup import GcsWorkspaceBackup
from pricor.entrypoints.wiring import workspace_backup_from_env
from pricor.ports.workspace_backup import NoWorkspaceBackup


def _write_valid_sqlite(path: Path) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t (id) VALUES (1)")
    return path.read_bytes()


def test_bucket_name_must_not_be_empty():
    with pytest.raises(ValueError, match="bucket_name"):
        GcsWorkspaceBackup("   ")


def test_save_uploads_source_to_bucket_blob(tmp_path):
    source = tmp_path / "test.sqlite"
    source.write_bytes(b"sqlite-data")

    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_blob = MagicMock()
    fake_client.bucket.return_value = fake_bucket
    fake_bucket.blob.return_value = fake_blob

    backup = GcsWorkspaceBackup("my-bucket", client=fake_client)
    backup.save("test-key", source)

    fake_client.bucket.assert_called_once_with("my-bucket")
    fake_bucket.blob.assert_called_once_with("workspaces/test-key.sqlite")
    fake_blob.upload_from_filename.assert_called_once_with(str(source))


def test_restore_returns_false_when_blob_does_not_exist(tmp_path):
    target = tmp_path / "restored.sqlite"

    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_blob = MagicMock()
    fake_blob.exists.return_value = False
    fake_client.bucket.return_value = fake_bucket
    fake_bucket.blob.return_value = fake_blob

    backup = GcsWorkspaceBackup("my-bucket", client=fake_client)
    result = backup.restore("missing-key", target)

    assert result is False
    assert not target.exists()


def test_restore_downloads_and_atomically_replaces_target(tmp_path):
    target = tmp_path / "ws" / "target.sqlite"
    expected_bytes: bytes = b""

    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_blob = MagicMock()
    fake_blob.exists.return_value = True

    def fake_download(filename):
        nonlocal expected_bytes
        expected_bytes = _write_valid_sqlite(Path(filename))

    fake_blob.download_to_filename.side_effect = fake_download
    fake_client.bucket.return_value = fake_bucket
    fake_bucket.blob.return_value = fake_blob

    backup = GcsWorkspaceBackup("my-bucket", client=fake_client)
    result = backup.restore("good-key", target)

    assert result is True
    assert target.is_file()
    assert target.read_bytes() == expected_bytes


def test_restore_rejects_corrupt_sqlite_and_leaves_no_target_or_temp_file(tmp_path):
    target = tmp_path / "ws" / "corrupt.sqlite"

    fake_client = MagicMock()
    fake_bucket = MagicMock()
    fake_blob = MagicMock()
    fake_blob.exists.return_value = True

    def fake_download(filename):
        Path(filename).write_bytes(b"corrupt-not-sqlite-header")

    fake_blob.download_to_filename.side_effect = fake_download
    fake_client.bucket.return_value = fake_bucket
    fake_bucket.blob.return_value = fake_blob

    backup = GcsWorkspaceBackup("my-bucket", client=fake_client)
    with pytest.raises(sqlite3.DatabaseError):
        backup.restore("bad-key", target)

    assert not target.exists()
    assert list((tmp_path / "ws").glob("*.tmp")) == []


def test_wiring_returns_gcs_backup_when_bucket_configured():
    backup = workspace_backup_from_env({"PRICOR_WORKSPACES_BUCKET": "demo-bucket"})
    assert isinstance(backup, GcsWorkspaceBackup)
    assert backup._bucket_name == "demo-bucket"


def test_wiring_returns_no_backup_when_bucket_not_configured():
    assert isinstance(workspace_backup_from_env({}), NoWorkspaceBackup)
    assert isinstance(workspace_backup_from_env({"PRICOR_WORKSPACES_BUCKET": ""}), NoWorkspaceBackup)
