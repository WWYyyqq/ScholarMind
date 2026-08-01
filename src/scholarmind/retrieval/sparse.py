"""Dependency-free BM25 retrieval suitable for local development and tests."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from ..models import Evidence
from ._text import tokenize
from .types import SearchResult


class SparseRetriever:
    """In-memory BM25 implementation with deterministic tie-breaking."""

    def __init__(
        self,
        evidence: Iterable[Evidence],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """Build BM25 corpus statistics with validated tuning parameters."""
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between zero and one")
        self.k1 = k1
        self.b = b
        self.replace(evidence)

    def replace(self, evidence: Iterable[Evidence]) -> None:
        """Atomically rebuild the BM25 corpus statistics."""
        items_by_id = {item.evidence_id: item for item in evidence}
        self._evidence = tuple(items_by_id[key] for key in sorted(items_by_id))
        self._term_frequencies = tuple(
            Counter(tokenize(item.text)) for item in self._evidence
        )
        self._lengths = tuple(sum(frequencies.values()) for frequencies in self._term_frequencies)
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        self._document_frequency: Counter[str] = Counter()
        for frequencies in self._term_frequencies:
            self._document_frequency.update(frequencies.keys())

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Rank evidence by BM25 score."""
        if limit < 1:
            raise ValueError("limit must be positive")
        query_terms = Counter(tokenize(query))
        if not query_terms or not self._evidence:
            return []
        corpus_size = len(self._evidence)
        scored: list[tuple[Evidence, float]] = []
        for item, frequencies, document_length in zip(
            self._evidence, self._term_frequencies, self._lengths
        ):
            score = 0.0
            for term, query_frequency in query_terms.items():
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_document_frequency = math.log(
                    1
                    + (corpus_size - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                length_ratio = (
                    document_length / self._average_length
                    if self._average_length
                    else 0.0
                )
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length_ratio
                )
                score += (
                    query_frequency
                    * inverse_document_frequency
                    * term_frequency
                    * (self.k1 + 1)
                    / denominator
                )
            if score > 0:
                scored.append((item, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].evidence_id))
        return [
            SearchResult(
                evidence=item,
                score=score,
                rank=rank,
                sparse_score=score,
                sparse_rank=rank,
            )
            for rank, (item, score) in enumerate(scored[:limit], start=1)
        ]
