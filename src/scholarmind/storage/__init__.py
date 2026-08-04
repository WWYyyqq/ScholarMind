"""Persistence abstractions and implementations."""

from .memory import InMemoryEvidenceRepository
from .postgres import OptionalPostgresDependencyError, PostgresEvidenceRepository
from .repository import (
    EmbeddingRepository,
    EvidenceRepository,
    RepositoryIntegrityError,
    VectorEvidenceRepository,
)

__all__ = [
    "EmbeddingRepository",
    "EvidenceRepository",
    "InMemoryEvidenceRepository",
    "OptionalPostgresDependencyError",
    "PostgresEvidenceRepository",
    "RepositoryIntegrityError",
    "VectorEvidenceRepository",
]
