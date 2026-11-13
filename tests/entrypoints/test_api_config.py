import pytest
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app


def make_client(model_provider: str = "ollama", demo: bool = False):
    use_case = ImportFirstTime(
        FileSpreadsheetReader(), InMemoryImportSessionRepository(), []
    )
    deps = ApiDependencies(
        use_case,
        model_provider=model_provider,
        demo=demo,
    )
    app = create_app(deps)
    return TestClient(app)


def test_get_config_returns_provider_and_demo_flag():
    client = make_client(model_provider="gemini", demo=True)

    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == {
        "model_provider": "gemini",
        "demo": True,
        "workspaces": False,
    }


def test_get_config_defaults():
    client = make_client()

    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == {
        "model_provider": "ollama",
        "demo": False,
        "workspaces": False,
    }


@pytest.mark.parametrize(
    ("demo_env", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("Yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
    ],
)
def test_demo_flag_parsing_in_wiring(demo_env, expected):
    from pricor.entrypoints.wiring import demo_from_env

    assert demo_from_env({"PRICOR_DEMO": demo_env}) is expected


def test_config_exposes_only_the_provider_the_demo_flag_and_workspaces():
    response = make_client(model_provider="gemini", demo=True).get("/config")

    assert set(response.json()) == {"model_provider", "demo", "workspaces"}
