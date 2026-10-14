"""The API server also serves the built web app (src/pricor/web_dist in a normal checkout)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app


def make_client(web_dist: Path | None) -> TestClient:
    use_case = ImportFirstTime(
        FileSpreadsheetReader(), InMemoryImportSessionRepository(), [], None
    )
    app = create_app(ApiDependencies(use_case, web_dist=web_dist))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><title>Pricor</title><div id=root></div>")
    (site / "assets" / "app.js").write_text("console.log('pricor')")
    (site / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the site")
    return site


def test_root_serves_the_app_shell(dist):
    response = make_client(dist).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id=root>" in response.text


def test_built_assets_and_root_files_are_served(dist):
    client = make_client(dist)
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text
    assert client.get("/favicon.svg").text == "<svg/>"


def test_unknown_client_routes_fall_back_to_the_shell(dist):
    response = make_client(dist).get("/review/anything")
    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_api_paths_keep_working_and_keep_their_json_errors(dist):
    client = make_client(dist)
    missing = client.get("/imports/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "session_not_found"
    # An unknown path under an API prefix is a JSON 404, not the HTML shell.
    unknown = client.get("/imports/does-not-exist/nothing-here")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_files_outside_the_site_are_never_served(dist):
    client = make_client(dist)
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt"):
        response = client.get(path)
        assert "outside the site" not in response.text, path


def test_a_missing_build_explains_how_to_make_one(tmp_path):
    response = make_client(tmp_path / "not-built").get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "npm --prefix web ci" in response.text
    assert "npm --prefix web run build" in response.text


def test_the_api_works_without_a_build(tmp_path):
    client = make_client(tmp_path / "not-built")
    assert client.get("/imports/does-not-exist").status_code == 404
    assert client.get("/docs").status_code == 200


def test_no_web_dist_means_api_only():
    client = make_client(None)
    assert client.get("/").status_code == 404
