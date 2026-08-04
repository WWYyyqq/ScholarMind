"""Retriever ports and result contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import Field

from ..models import Evidence
from ..models._base import DomainModel


class EmbeddingProvider(Protocol):
    """Small provider-neutral embedding interface."""

    def embed_query(self, text: str) -> Sequence[float]:
        """Embed one query."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Embed a batch of evidence passages."""
        ...


class SearchResult(DomainModel):
    """One ranked evidence result with optional component diagnostics."""

    evidence: Evidence
    score: float
    rank: int = Field(ge=1)
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = Field(default=None, ge=1)
    sparse_rank: int | None = Field(default=None, ge=1)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    reranker_score: float | None = None


class Retriever(Protocol):
    """Common search port used by File Researcher and hybrid fusion."""

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Return evidence ordered from most to least relevant."""
        ...
