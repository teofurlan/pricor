import pytest
from fastapi.testclient import TestClient

from pricor.entrypoints.wiring import app_for_env, workspaces_dir_from_env, workspaces_max_open_from_env


def base_env(tmp_path):
    return {"PRICOR_DB": str(tmp_path / "local.db"), "PRICOR_LAYA_MODEL": str(tmp_path / "absent")}


def test_workspaces_are_off_unless_a_directory_is_configured(tmp_path):
    assert workspaces_dir_from_env({}) is None
    assert workspaces_dir_from_env({"PRICOR_WORKSPACES_DIR": "  "}) is None
    assert workspaces_dir_from_env({"PRICOR_WORKSPACES_DIR": str(tmp_path)}) == tmp_path


def test_open_workspaces_default_to_sixteen_and_must_be_positive():
    assert workspaces_max_open_from_env({}) == 16
    assert workspaces_max_open_from_env({"PRICOR_WORKSPACES_MAX_OPEN": "3"}) == 3
    for bad in ("0", "-1", "many"):
        with pytest.raises(ValueError, match="PRICOR_WORKSPACES_MAX_OPEN"):
            workspaces_max_open_from_env({"PRICOR_WORKSPACES_MAX_OPEN": bad})


def test_local_mode_is_unchanged_one_database_and_no_workspace_needed(tmp_path):
    client = TestClient(app_for_env(base_env(tmp_path)), raise_server_exceptions=False)

    assert client.get("/config").json() == {"model_provider": "ollama", "demo": False, "workspaces": False}
    missing = client.get("/imports/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] != "workspace_required"
    no_workspace = client.get("/workspace")
    assert not no_workspace.headers.get("content-type", "").startswith("application/json") or (
        "link" not in no_workspace.json()
    )
    assert "pricor_workspace" not in no_workspace.headers.get("set-cookie", "")
    assert (tmp_path / "local.db").is_file()


def test_the_workspaces_directory_turns_on_private_workspaces(tmp_path):
    env = {**base_env(tmp_path), "PRICOR_WORKSPACES_DIR": str(tmp_path / "ws")}
    client = TestClient(app_for_env(env), raise_server_exceptions=False)

    assert client.get("/config").json()["workspaces"] is True
    assert client.get("/imports/nope").json()["error"]["code"] == "workspace_required"
    assert "/w/" in client.get("/workspace").json()["link"]
    assert client.get("/imports/nope").status_code == 404
    assert not (tmp_path / "local.db").exists()
