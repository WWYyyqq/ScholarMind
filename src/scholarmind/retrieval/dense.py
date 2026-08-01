"""Provider-neutral dense retrieval with a deterministic local embedder."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Protocol

from ..models import Evidence
from ._text import tokenize
from .types import EmbeddingProvider, SearchResult


def _normalize(values: Sequence[float]) -> tuple[float, ...]:
    """L2-normalize a vector, preserving a zero vector."""
    vector = tuple(float(value) for value in values)
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return tuple(0.0 for _ in vector)
    return tuple(value / magnitude for value in vector)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Compute cosine similarity with explicit dimension validation."""
    if len(left) != len(right):
        raise ValueError(
            f"embedding dimension mismatch: query={len(left)}, document={len(right)}"
        )
    normalized_left = _normalize(left)
    normalized_right = _normalize(right)
    return sum(a * b for a, b in zip(normalized_left, normalized_right))


class HashingEmbedder:
    """A zero-download lexical hashing baseline implementing the dense port."""

    def __init__(self, dimension: int = 256) -> None:
        """Configure the deterministic hashing vector dimension."""
        if dimension < 8:
            raise ValueError("dimension must be at least 8")
        self.dimension = dimension

    def _embed(self, text: str) -> tuple[float, ...]:
        counts = Counter(tokenize(text))
        values = [0.0] * self.dimension
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimension
            values[index] += 1.0 + math.log(count)
        return _normalize(values)

    def embed_query(self, text: str) -> Sequence[float]:
        """Embed one query locally."""
        return self._embed(text)

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Embed passages locally without network or model downloads."""
        return [self._embed(text) for text in texts]


class DenseRetriever:
    """In-memory cosine retriever backed by any EmbeddingProvider."""

    def __init__(
        self,
        evidence: Iterable[Evidence],
        *,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        """Build an in-memory dense index for the supplied evidence."""
        self.embedder = embedder or HashingEmbedder()
        self.replace(evidence)

    def replace(self, evidence: Iterable[Evidence]) -> None:
        """Atomically rebuild the in-memory dense index."""
        items_by_id = {item.evidence_id: item for item in evidence}
        items = tuple(items_by_id[key] for key in sorted(items_by_id))
        vectors = tuple(
            tuple(float(value) for value in vector)
            for vector in self.embedder.embed_documents([item.text for item in items])
        )
        if len(vectors) != len(items):
            raise ValueError("embed_documents returned a different number of vectors")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) > 1 or (dimensions and next(iter(dimensions)) == 0):
            raise ValueError("document embeddings must use one non-zero dimension")
        self._evidence = items
        self._vectors = vectors

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Rank in-memory evidence by cosine similarity."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not query.strip() or not self._evidence:
            return []
        query_vector = tuple(float(value) for value in self.embedder.embed_query(query))
        scored = [
            (item, _cosine(query_vector, vector))
            for item, vector in zip(self._evidence, self._vectors)
        ]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0].evidence_id))
        return [
            SearchResult(
                evidence=item,
                score=score,
                rank=rank,
                dense_score=score,
                dense_rank=rank,
            )
            for rank, (item, score) in enumerate(scored[:limit], start=1)
        ]


class PgvectorSearchPort(Protocol):
    """Structural port implemented by PostgresEvidenceRepository."""

    def dense_search(
        self,
        query_embedding: Sequence[float],
        *,
        model: str,
        limit: int = 8,
    ) -> tuple[tuple[Evidence, float], ...]:
        """Return database-ranked evidence and cosine similarity."""
        ...


class PostgresDenseRetriever:
    """Thin adapter from an EmbeddingProvider to pgvector repository search."""

    def __init__(
        self,
        repository: PgvectorSearchPort,
        *,
        embedder: EmbeddingProvider,
        model: str,
    ) -> None:
        """Bind an embedding provider to a pgvector-capable repository."""
        self.repository = repository
        self.embedder = embedder
        self.model = model

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Embed a query and delegate cosine ranking to PostgreSQL."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not query.strip():
            return []
        rows = self.repository.dense_search(
            self.embedder.embed_query(query), model=self.model, limit=limit
        )
        return [
            SearchResult(
                evidence=evidence,
                score=score,
                rank=rank,
                dense_score=score,
                dense_rank=rank,
            )
            for rank, (evidence, score) in enumerate(rows, start=1)
        ]
