import pytest

from pricor.adapters.gemini_client import GeminiChatClient
from pricor.adapters.gemini_embedder import GeminiEmbedder
from pricor.adapters.ollama_client import OllamaClient
from pricor.adapters.ollama_embedder import OllamaEmbedder
from pricor.application.cascade import UNCALIBRATED_THRESHOLD
from pricor.entrypoints.wiring import (
    build_stages,
    dependencies_from_env,
)


def test_defaults_to_ollama_provider_unchanged():
    deps = dependencies_from_env({"PRICOR_DB": ":memory:"})
    assert isinstance(deps.memory._embedder, OllamaEmbedder)
    # Advisor, question_helper, output_format all use OllamaClient
    assert isinstance(deps.question_helper._client, OllamaClient)
    assert deps.model_provider == "ollama"
    assert deps.demo is False
    assert deps.memory._embedder.model == "bge-m3"
    assert deps.memory._embedder.base_url == "http://localhost:11434"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_provider_means_the_default_ollama(value):
    deps = dependencies_from_env({"PRICOR_DB": ":memory:", "PRICOR_MODEL_PROVIDER": value})

    assert deps.model_provider == "ollama"
    assert isinstance(deps.question_helper._client, OllamaClient)


def test_provider_ignores_case_and_surrounding_spaces():
    env = {
        "PRICOR_DB": ":memory:",
        "PRICOR_MODEL_PROVIDER": " Gemini ",
        "PRICOR_GEMINI_API_KEY": "test-key-123",
    }
    deps = dependencies_from_env(env)

    assert deps.model_provider == "gemini"
    assert isinstance(deps.question_helper._client, GeminiChatClient)
    gemma = next(stage for stage in build_stages(env, deps.question_helper._client) if stage.name == "gemma")
    assert (gemma.threshold, gemma.threshold_calibrated) == (UNCALIBRATED_THRESHOLD, False)


def test_invalid_provider_raises_value_error():
    with pytest.raises(ValueError, match="PRICOR_MODEL_PROVIDER"):
        dependencies_from_env({"PRICOR_DB": ":memory:", "PRICOR_MODEL_PROVIDER": "anthropic"})


def test_gemini_provider_requires_api_key():
    with pytest.raises(ValueError, match="PRICOR_GEMINI_API_KEY"):
        dependencies_from_env({"PRICOR_DB": ":memory:", "PRICOR_MODEL_PROVIDER": "gemini"})

    with pytest.raises(ValueError, match="PRICOR_GEMINI_API_KEY"):
        dependencies_from_env({
            "PRICOR_DB": ":memory:",
            "PRICOR_MODEL_PROVIDER": "gemini",
            "PRICOR_GEMINI_API_KEY": "   ",
        })


def test_a_blank_api_key_is_rejected_without_echoing_the_value():
    with pytest.raises(ValueError) as raised:
        dependencies_from_env({
            "PRICOR_DB": ":memory:",
            "PRICOR_MODEL_PROVIDER": "gemini",
            "PRICOR_GEMINI_API_KEY": "  	 ",
        })

    message = str(raised.value)
    assert "PRICOR_GEMINI_API_KEY is required" in message
    assert "	" not in message and "None" not in message


def test_gemini_provider_wires_gemini_adapters_and_options():
    env = {
        "PRICOR_DB": ":memory:",
        "PRICOR_MODEL_PROVIDER": "gemini",
        "PRICOR_GEMINI_API_KEY": "test-key-123",
        "PRICOR_GEMINI_MODEL": "custom-gemma",
        "PRICOR_GEMINI_EMBED_MODEL": "custom-embed",
        "PRICOR_GEMINI_TIMEOUT": "45",
        "PRICOR_DEMO": "yes",
    }
    deps = dependencies_from_env(env)

    assert deps.model_provider == "gemini"
    assert deps.demo is True
    assert isinstance(deps.memory._embedder, GeminiEmbedder)
    assert deps.memory._embedder.model == "custom-embed@768"
    assert deps.memory._embedder.timeout == 45.0

    client = deps.question_helper._client
    assert isinstance(client, GeminiChatClient)
    assert client.model == "custom-gemma"
    assert client.timeout == 45.0


def test_gemma_stage_uncalibrated_under_gemini_without_explicit_calibration():
    client = GeminiChatClient(api_key="test-key")
    stages = build_stages(
        {"PRICOR_MODEL_PROVIDER": "gemini"},
        client,
        laya_unavailable_reason=lambda _: "disabled",
    )
    gemma_stage = next(s for s in stages if s.name == "gemma")
    assert gemma_stage.threshold_calibrated is False
    assert gemma_stage.threshold == UNCALIBRATED_THRESHOLD


def test_gemma_stage_calibrated_under_ollama():
    client = OllamaClient()
    stages = build_stages(
        {},
        client,
        laya_unavailable_reason=lambda _: "disabled",
    )
    gemma_stage = next(s for s in stages if s.name == "gemma")
    assert gemma_stage.threshold_calibrated is True


def test_gemma_stage_uses_explicit_calibration_file_under_gemini(tmp_path):
    cal_file = tmp_path / "custom_cal.json"
    cal_file.write_text(
        '{"calibrated_on": "2026-10-26", "cascade_order": "laya>gemma", "stages": {"laya": {"threshold": 0.8}, "gemma": {"threshold": 0.88}}}'
    )
    client = GeminiChatClient(api_key="test-key")
    stages = build_stages(
        {"PRICOR_MODEL_PROVIDER": "gemini", "PRICOR_CALIBRATION": str(cal_file)},
        client,
        laya_unavailable_reason=lambda _: "disabled",
    )
    gemma_stage = next(s for s in stages if s.name == "gemma")
    assert gemma_stage.threshold_calibrated is True
    assert gemma_stage.threshold == 0.88
