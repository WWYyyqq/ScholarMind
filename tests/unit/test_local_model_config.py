"""Tests for the optional OpenAI-compatible local model endpoint."""

from open_deep_research.configuration import Configuration
from open_deep_research.utils import get_base_url_for_model


def test_openai_base_url_from_environment(monkeypatch):
    """Read the local endpoint from the project environment."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")

    config = Configuration.from_runnable_config({})

    assert config.openai_base_url == "http://127.0.0.1:8000/v1"
    assert (
        get_base_url_for_model("openai:qwen3-14b-local", {})
        == "http://127.0.0.1:8000/v1"
    )


def test_openai_base_url_is_not_used_for_other_providers(monkeypatch):
    """Avoid passing OpenAI endpoint settings to unrelated providers."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")

    assert get_base_url_for_model("anthropic:claude-sonnet-4", {}) is None
