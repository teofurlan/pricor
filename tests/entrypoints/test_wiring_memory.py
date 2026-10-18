import pytest

from pricor.adapters.ollama_embedder import OllamaEmbedder
from pricor.adapters.sqlite_memory_store import SqliteMemoryStore
from pricor.application.manage_memory import ManageMemory
from pricor.entrypoints.wiring import dependencies_from_env


def test_dependencies_wire_memory_to_the_shared_database_and_ollama_settings():
    dependencies = dependencies_from_env(
        {
            "PRICOR_DB": ":memory:",
            "PRICOR_OLLAMA_URL": "http://ollama.test:1234/",
            "PRICOR_OLLAMA_TIMEOUT": "12.5",
            "PRICOR_EMBED_MODEL": "custom-embed",
            "PRICOR_MEMORY_TOP_K": "7",
        }
    )

    assert isinstance(dependencies.memory, ManageMemory)
    assert isinstance(dependencies.memory._store, SqliteMemoryStore)
    assert isinstance(dependencies.memory._embedder, OllamaEmbedder)
    assert dependencies.memory._store._db is dependencies.use_case._repository._db
    assert dependencies.memory._embedder.base_url == "http://ollama.test:1234"
    assert dependencies.memory._embedder.model == "custom-embed"
    assert dependencies.memory._embedder.timeout == 12.5


def test_default_embedding_model_is_bge_m3():
    dependencies = dependencies_from_env({"PRICOR_DB": ":memory:"})

    assert dependencies.memory._embedder.model == "bge-m3"


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "many"])
def test_memory_top_k_must_be_a_positive_integer(value):
    with pytest.raises(ValueError, match="PRICOR_MEMORY_TOP_K must be a positive integer"):
        dependencies_from_env(
            {"PRICOR_DB": ":memory:", "PRICOR_MEMORY_TOP_K": value}
        )
