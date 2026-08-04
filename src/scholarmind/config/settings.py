"""Project-scoped settings without global environment mutation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum

from pydantic import Field, model_validator

from ..models._base import DomainModel


class StorageBackend(str, Enum):
    """Supported persistence backends."""

    MEMORY = "memory"
    POSTGRES = "postgres"


class ScholarMindSettings(DomainModel):
    """Runtime settings read explicitly from ScholarMind-prefixed variables."""

    storage_backend: StorageBackend = StorageBackend.MEMORY
    postgres_dsn: str | None = Field(default=None, repr=False)
    embedding_model: str = "hashing-local-v1"
    embedding_dimension: int = Field(default=256, ge=8)
    embedding_base_url: str = "http://[::1]:8001/v1"
    embedding_api_key: str = Field(default="local-not-required", repr=False)
    embedding_query_instruction: str = (
        "Given an academic research question, retrieve relevant paper passages."
    )
    retrieval_limit: int = Field(default=8, ge=1, le=100)
    dense_weight: float = Field(default=1.0, gt=0.0)
    sparse_weight: float = Field(default=1.0, gt=0.0)
    rrf_k: int = Field(default=60, ge=1)

    @model_validator(mode="after")
    def postgres_requires_dsn(self) -> ScholarMindSettings:
        """Fail early when a selected database backend is not configured."""
        if self.storage_backend is StorageBackend.POSTGRES and not self.postgres_dsn:
            raise ValueError("SCHOLARMIND_POSTGRES_DSN is required for postgres storage")
        return self

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> ScholarMindSettings:
        """Load only project-prefixed values from a supplied environment mapping."""
        values = os.environ if environ is None else environ
        raw: dict[str, object] = {}
        mapping = {
            "SCHOLARMIND_STORAGE_BACKEND": "storage_backend",
            "SCHOLARMIND_POSTGRES_DSN": "postgres_dsn",
            "SCHOLARMIND_EMBEDDING_MODEL": "embedding_model",
            "SCHOLARMIND_EMBEDDING_DIMENSION": "embedding_dimension",
            "SCHOLARMIND_EMBEDDING_BASE_URL": "embedding_base_url",
            "SCHOLARMIND_EMBEDDING_API_KEY": "embedding_api_key",
            "SCHOLARMIND_EMBEDDING_QUERY_INSTRUCTION": (
                "embedding_query_instruction"
            ),
            "SCHOLARMIND_RETRIEVAL_LIMIT": "retrieval_limit",
            "SCHOLARMIND_DENSE_WEIGHT": "dense_weight",
            "SCHOLARMIND_SPARSE_WEIGHT": "sparse_weight",
            "SCHOLARMIND_RRF_K": "rrf_k",
        }
        for env_name, field_name in mapping.items():
            if env_name in values and values[env_name] != "":
                raw[field_name] = values[env_name]
        return cls.model_validate(raw)
