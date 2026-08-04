"""Reciprocal-rank fusion across dense and sparse evidence retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Evidence
from .types import Retriever, SearchResult


@dataclass
class _FusionEntry:
    evidence: Evidence
    score: float = 0.0
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None


def reciprocal_rank_fusion(
    dense_results: list[SearchResult],
    sparse_results: list[SearchResult],
    *,
    limit: int = 5,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[SearchResult]:
    """Fuse independent result lists without assuming comparable raw scores."""
    if limit < 1:
        raise ValueError("limit must be positive")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    if dense_weight <= 0 or sparse_weight <= 0:
        raise ValueError("fusion weights must be positive")
    entries: dict[str, _FusionEntry] = {}
    for source_name, results, weight in (
        ("dense", dense_results, dense_weight),
        ("sparse", sparse_results, sparse_weight),
    ):
        seen: set[str] = set()
        for fallback_rank, result in enumerate(results, start=1):
            evidence_id = result.evidence.evidence_id
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            rank = result.rank if result.rank >= 1 else fallback_rank
            entry = entries.setdefault(
                evidence_id, _FusionEntry(evidence=result.evidence)
            )
            entry.score += weight / (rrf_k + rank)
            if source_name == "dense":
                entry.dense_score = result.score
                entry.dense_rank = rank
            else:
                entry.sparse_score = result.score
                entry.sparse_rank = rank
    ordered = sorted(
        entries.values(),
        key=lambda entry: (-entry.score, entry.evidence.evidence_id),
    )
    return [
        SearchResult(
            evidence=entry.evidence,
            score=entry.score,
            rank=rank,
            dense_score=entry.dense_score,
            sparse_score=entry.sparse_score,
            dense_rank=entry.dense_rank,
            sparse_rank=entry.sparse_rank,
        )
        for rank, entry in enumerate(ordered[:limit], start=1)
    ]


class HybridRetriever:
    """Retrieve broad candidates, then combine rank evidence using weighted RRF."""

    def __init__(
        self,
        dense: Retriever,
        sparse: Retriever,
        *,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        candidate_multiplier: int = 4,
    ) -> None:
        """Configure weighted reciprocal-rank fusion over two retrievers."""
        if candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be positive")
        self.dense = dense
        self.sparse = sparse
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.candidate_multiplier = candidate_multiplier

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Return RRF-ranked evidence with component scores and ranks."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not query.strip():
            return []
        candidate_limit = limit * self.candidate_multiplier
        dense_results = self.dense.search(query, limit=candidate_limit)
        sparse_results = self.sparse.search(query, limit=candidate_limit)
        return reciprocal_rank_fusion(
            dense_results,
            sparse_results,
            limit=limit,
            rrf_k=self.rrf_k,
            dense_weight=self.dense_weight,
            sparse_weight=self.sparse_weight,
        )
