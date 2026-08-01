"""Batch evidence embedding with repository-neutral persistence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from ..models import Evidence
from ..storage.repository import EmbeddingRepository
from .types import EmbeddingProvider


@dataclass(frozen=True)
class IndexingResult:
    """Deterministic summary returned after an evidence indexing run."""

    model: str
    indexed_count: int
    evidence_ids: tuple[str, ...]
    embedding_dimension: int | None


class EvidenceIndexer:
    """Embed evidence in bounded batches and persist model-qualified vectors."""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        *,
        model: str,
        batch_size: int = 32,
    ) -> None:
        """Configure a provider, its stable model name, and a positive batch size."""
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model must not be empty")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._embedder = embedder
        self._model = normalized_model
        self._batch_size = batch_size

    def index(
        self,
        evidence: Iterable[Evidence],
        repository: EmbeddingRepository,
    ) -> IndexingResult:
        """Embed unique evidence in stable ID order and upsert each vector."""
        unique: dict[str, Evidence] = {}
        for item in evidence:
            previous = unique.get(item.evidence_id)
            if previous is not None and previous != item:
                raise ValueError(
                    f"conflicting evidence records share {item.evidence_id!r}"
                )
            unique[item.evidence_id] = item
        ordered = tuple(unique[key] for key in sorted(unique))

        embedding_dimension: int | None = None
        indexed_ids: list[str] = []
        for offset in range(0, len(ordered), self._batch_size):
            batch = ordered[offset : offset + self._batch_size]
            raw_vectors = self._embedder.embed_documents(
                [item.text for item in batch]
            )
            vectors = tuple(
                tuple(float(value) for value in vector) for vector in raw_vectors
            )
            if len(vectors) != len(batch):
                raise ValueError(
                    "embedding provider returned a different number of vectors "
                    "than input passages"
                )
            for vector in vectors:
                if not vector:
                    raise ValueError("embedding vectors must not be empty")
                if not all(isfinite(value) for value in vector):
                    raise ValueError("embedding values must be finite")
                if embedding_dimension is None:
                    embedding_dimension = len(vector)
                elif len(vector) != embedding_dimension:
                    raise ValueError(
                        "embedding provider returned inconsistent vector dimensions"
                    )
            for item, vector in zip(batch, vectors, strict=True):
                repository.upsert_embedding(
                    item.evidence_id,
                    vector,
                    model=self._model,
                )
                indexed_ids.append(item.evidence_id)

        return IndexingResult(
            model=self._model,
            indexed_count=len(indexed_ids),
            evidence_ids=tuple(indexed_ids),
            embedding_dimension=embedding_dimension,
        )
