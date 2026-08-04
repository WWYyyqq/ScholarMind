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


def test_postgres_backend_requires_project_dsn() -> None:
    with pytest.raises(ValidationError, match="SCHOLARMIND_POSTGRES_DSN"):
        ScholarMindSettings.from_env({"SCHOLARMIND_STORAGE_BACKEND": "postgres"})
