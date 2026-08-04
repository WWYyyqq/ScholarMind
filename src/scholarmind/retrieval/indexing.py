"""Resumable batch evidence embedding with failure isolation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from math import isfinite

from ..models import Evidence
from ..storage.repository import EmbeddingRepository
from .types import EmbeddingProvider


@dataclass(frozen=True)
class IndexingFailure:
    """One evidence record that could not be embedded or persisted."""

    evidence_id: str
    error_type: str
    message: str


@dataclass(frozen=True)
class IndexingProgress:
    """Durable progress event emitted after a terminal indexing operation."""

    status: str
    evidence_ids: tuple[str, ...]
    total_count: int
    completed_count: int
    indexed_count: int
    skipped_count: int
    failed_count: int
    failure: IndexingFailure | None = None


@dataclass(frozen=True)
class IndexingResult:
    """Deterministic summary returned after an evidence indexing run."""

    model: str
    indexed_count: int
    evidence_ids: tuple[str, ...]
    embedding_dimension: int | None
    total_count: int = 0
    skipped_count: int = 0
    skipped_evidence_ids: tuple[str, ...] = ()
    failed_count: int = 0
    failures: tuple[IndexingFailure, ...] = ()

    @property
    def complete(self) -> bool:
        """Return whether every requested record is now indexed."""
        return self.failed_count == 0 and (
            self.indexed_count + self.skipped_count == self.total_count
        )


ProgressCallback = Callable[[IndexingProgress], None]


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
        *,
        resume: bool = False,
        continue_on_error: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> IndexingResult:
        """Embed evidence, optionally skipping committed vectors and isolating failures."""
        unique: dict[str, Evidence] = {}
        for item in evidence:
            previous = unique.get(item.evidence_id)
            if previous is not None and previous != item:
                raise ValueError(
                    f"conflicting evidence records share {item.evidence_id!r}"
                )
            unique[item.evidence_id] = item
        ordered = tuple(unique[key] for key in sorted(unique))
        total_count = len(ordered)

        existing_ids = (
            set(repository.list_embedding_ids(model=self._model)) if resume else set()
        )
        requested_ids = set(unique)
        skipped_ids = tuple(sorted(existing_ids & requested_ids))
        pending = tuple(
            item for item in ordered if item.evidence_id not in existing_ids
        )

        indexed_ids: set[str] = set()
        failures: list[IndexingFailure] = []
        embedding_dimension: int | None = None
        reported_skipped_count = 0

        def emit(
            status: str,
            evidence_ids: Sequence[str],
            failure: IndexingFailure | None = None,
        ) -> None:
            if on_progress is None:
                return
            on_progress(
                IndexingProgress(
                    status=status,
                    evidence_ids=tuple(evidence_ids),
                    total_count=total_count,
                    completed_count=(
                        reported_skipped_count
                        + len(indexed_ids)
                        + len(failures)
                    ),
                    indexed_count=len(indexed_ids),
                    skipped_count=reported_skipped_count,
                    failed_count=len(failures),
                    failure=failure,
                )
            )

        for offset in range(0, len(skipped_ids), self._batch_size):
            skipped_batch = skipped_ids[offset : offset + self._batch_size]
            reported_skipped_count += len(skipped_batch)
            emit("skipped", skipped_batch)

        def index_batch(batch: tuple[Evidence, ...]) -> None:
            nonlocal embedding_dimension
            try:
                vectors, embedding_dimension = self._embed_batch(
                    batch,
                    expected_dimension=embedding_dimension,
                )
                for item, vector in zip(batch, vectors, strict=True):
                    repository.upsert_embedding(
                        item.evidence_id,
                        vector,
                        model=self._model,
                    )
                    indexed_ids.add(item.evidence_id)
                emit("indexed", [item.evidence_id for item in batch])
            except Exception as exc:
                if not continue_on_error or not isinstance(exc, ValueError):
                    raise
                if len(batch) > 1:
                    midpoint = len(batch) // 2
                    index_batch(batch[:midpoint])
                    index_batch(batch[midpoint:])
                    return
                item = batch[0]
                failure = IndexingFailure(
                    evidence_id=item.evidence_id,
                    error_type=type(exc).__name__,
                    message=" ".join(str(exc).split()) or repr(exc),
                )
                failures.append(failure)
                emit("failed", (item.evidence_id,), failure)

        for offset in range(0, len(pending), self._batch_size):
            index_batch(pending[offset : offset + self._batch_size])

        ordered_indexed_ids = tuple(sorted(indexed_ids))
        return IndexingResult(
            model=self._model,
            total_count=total_count,
            indexed_count=len(ordered_indexed_ids),
            evidence_ids=ordered_indexed_ids,
            skipped_count=len(skipped_ids),
            skipped_evidence_ids=skipped_ids,
            failed_count=len(failures),
            failures=tuple(failures),
            embedding_dimension=embedding_dimension,
        )

    def _embed_batch(
        self,
        batch: tuple[Evidence, ...],
        *,
        expected_dimension: int | None,
    ) -> tuple[tuple[tuple[float, ...], ...], int]:
        """Embed and validate one batch before any vector is persisted."""
        raw_vectors = self._embedder.embed_documents([item.text for item in batch])
        vectors = tuple(
            tuple(float(value) for value in vector) for vector in raw_vectors
        )
        if len(vectors) != len(batch):
            raise ValueError(
                "embedding provider returned a different number of vectors "
                "than input passages"
            )

        dimension = expected_dimension
        for vector in vectors:
            if not vector:
                raise ValueError("embedding vectors must not be empty")
            if not all(isfinite(value) for value in vector):
                raise ValueError("embedding values must be finite")
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise ValueError(
                    "embedding provider returned inconsistent vector dimensions"
                )
        if dimension is None:
            raise ValueError("embedding batch must not be empty")
        return vectors, dimension
