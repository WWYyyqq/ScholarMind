"""Project-scoped configuration tests."""

import pytest
from pydantic import ValidationError

from scholarmind.config import ScholarMindSettings, StorageBackend


def test_defaults_require_no_service_or_global_environment() -> None:
    settings = ScholarMindSettings.from_env({})

    assert settings.storage_backend is StorageBackend.MEMORY
    assert settings.postgres_dsn is None
    assert settings.embedding_model == "hashing-local-v1"


def test_prefixed_environment_values_are_parsed() -> None:
    settings = ScholarMindSettings.from_env(
        {
            "DATABASE_URL": "must-be-ignored",
            "SCHOLARMIND_RETRIEVAL_LIMIT": "12",
            "SCHOLARMIND_EMBEDDING_DIMENSION": "384",
            "SCHOLARMIND_RRF_K": "30",
        }
    )

    assert settings.retrieval_limit == 12
    assert settings.embedding_dimension == 384
    assert settings.rrf_k == 30


def test_settings_load_local_embedding_endpoint() -> None:
    settings = ScholarMindSettings.from_env(
        {
            "SCHOLARMIND_EMBEDDING_MODEL": "qwen3-embedding-local",
            "SCHOLARMIND_EMBEDDING_DIMENSION": "1024",
            "SCHOLARMIND_EMBEDDING_BASE_URL": "http://127.0.0.1:8001/v1",
            "SCHOLARMIND_EMBEDDING_API_KEY": "test-key",
            "SCHOLARMIND_EMBEDDING_QUERY_INSTRUCTION": "retrieve papers",
        }
    )

    assert settings.embedding_model == "qwen3-embedding-local"
    assert settings.embedding_dimension == 1024
    assert settings.embedding_base_url == "http://127.0.0.1:8001/v1"
    assert settings.embedding_api_key == "test-key"
    assert settings.embedding_query_instruction == "retrieve papers"


def test_settings_load_project_scoped_semantic_verifier() -> None:
    settings = ScholarMindSettings.from_env(
        {
            "OPENAI_BASE_URL": "must-be-ignored",
            "SCHOLARMIND_VERIFICATION_MODE": "semantic",
            "SCHOLARMIND_VERIFIER_MODEL": "qwen3-verifier",
            "SCHOLARMIND_VERIFIER_BASE_URL": "http://127.0.0.1:8000/v1",
            "SCHOLARMIND_VERIFIER_API_KEY": "test-key",
            "SCHOLARMIND_VERIFIER_MINIMUM_CONFIDENCE": "0.8",
        }
    )

    assert settings.verification_mode == "semantic"
    assert settings.verifier_model == "qwen3-verifier"
    assert settings.verifier_base_url == "http://127.0.0.1:8000/v1"
    assert settings.verifier_api_key == "test-key"
    assert settings.verifier_minimum_confidence == 0.8


def test_postgres_backend_requires_project_dsn() -> None:
    with pytest.raises(ValidationError, match="SCHOLARMIND_POSTGRES_DSN"):
        ScholarMindSettings.from_env({"SCHOLARMIND_STORAGE_BACKEND": "postgres"})
