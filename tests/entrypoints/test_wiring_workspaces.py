import pytest
from fastapi.testclient import TestClient

from pricor.entrypoints.wiring import (
    app_for_env,
    rate_limit_from_env,
    workspaces_dir_from_env,
    workspaces_max_open_from_env,
)


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
    assert "/#w=" in client.get("/workspace").json()["link"]
    assert client.get("/imports/nope").status_code == 404
    assert not (tmp_path / "local.db").exists()


def test_rate_limit_config_defaults_on_in_hosted_mode_and_off_locally():
    assert rate_limit_from_env({}, hosted=False) is None
    hosted = rate_limit_from_env({}, hosted=True)
    assert hosted is not None
    assert hosted.general_rpm == 120
    assert hosted.heavy_rpm == 30
    assert hosted.trusted_proxies == 1

    # Explicitly setting 0 disables rate limiting even in hosted mode.
    assert rate_limit_from_env({"PRICOR_RATE_LIMIT_RPM": "0"}, hosted=True) is None

    # Explicitly setting a positive limit enables it locally too.
    local = rate_limit_from_env({"PRICOR_RATE_LIMIT_RPM": "10", "PRICOR_RATE_LIMIT_HEAVY_RPM": "4"}, hosted=False)
    assert local is not None
    assert local.general_rpm == 10
    assert local.heavy_rpm == 4
    assert local.trusted_proxies == 0

    # When general_rpm is set lower than default heavy_rpm and heavy is unset, heavy is capped at general.
    tight = rate_limit_from_env({"PRICOR_RATE_LIMIT_RPM": "10"}, hosted=True)
    assert tight is not None
    assert tight.heavy_rpm == 10


@pytest.mark.parametrize(
    ("env", "match"),
    [
        ({"PRICOR_RATE_LIMIT_RPM": "-1"}, "PRICOR_RATE_LIMIT_RPM"),
        ({"PRICOR_RATE_LIMIT_RPM": "fast"}, "PRICOR_RATE_LIMIT_RPM"),
        ({"PRICOR_RATE_LIMIT_HEAVY_RPM": "0"}, "PRICOR_RATE_LIMIT_HEAVY_RPM"),
        ({"PRICOR_RATE_LIMIT_HEAVY_RPM": "-5"}, "PRICOR_RATE_LIMIT_HEAVY_RPM"),
        ({"PRICOR_RATE_LIMIT_HEAVY_RPM": "nope"}, "PRICOR_RATE_LIMIT_HEAVY_RPM"),
        ({"PRICOR_TRUSTED_PROXIES": "-1"}, "PRICOR_TRUSTED_PROXIES"),
        ({"PRICOR_TRUSTED_PROXIES": "cloud"}, "PRICOR_TRUSTED_PROXIES"),
    ],
)
def test_rate_limit_env_rejects_invalid_values(env, match):
    with pytest.raises(ValueError, match=match):
        rate_limit_from_env(env, hosted=True)


def test_hosted_app_enforces_rate_limit_end_to_end_and_allows_opting_out(tmp_path):
    env = {
        **base_env(tmp_path),
        "PRICOR_WORKSPACES_DIR": str(tmp_path / "ws"),
        "PRICOR_RATE_LIMIT_RPM": "2",
        "PRICOR_RATE_LIMIT_HEAVY_RPM": "1",
    }
    client = TestClient(app_for_env(env), raise_server_exceptions=False)

    # Public events endpoint uses general bucket (limit 2).
    assert client.post("/events", json={"event": "visit", "group": None}).status_code == 204
    assert client.post("/events", json={"event": "visit", "group": None}).status_code == 204
    limited = client.post("/events", json={"event": "visit", "group": None})
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"

    # Public warm-up endpoint uses heavy bucket (limit 1).
    assert client.post("/warm-up").status_code == 200
    assert client.post("/warm-up").status_code == 429

    # Opting out via PRICOR_RATE_LIMIT_RPM=0 removes the limit.
    disabled = TestClient(
        app_for_env({**env, "PRICOR_RATE_LIMIT_RPM": "0"}), raise_server_exceptions=False
    )
    for _ in range(5):
        assert disabled.post("/events", json={"event": "visit", "group": None}).status_code == 204
        assert disabled.post("/warm-up").status_code == 200

