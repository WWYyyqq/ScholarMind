"""Ranking tests for dense, BM25, and hybrid RRF retrieval."""

from collections.abc import Sequence

from scholarmind.models import Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.retrieval import (
    DenseRetriever,
    HashingEmbedder,
    HybridRetriever,
    SearchResult,
    SparseRetriever,
    reciprocal_rank_fusion,
)


def _corpus():
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Retrieval Corpus",
        uri="papers/retrieval.pdf",
    )
    texts = (
        "PostgreSQL pgvector performs dense vector similarity search.",
        "BM25 is a sparse lexical retrieval ranking function.",
        "Reciprocal rank fusion combines dense and sparse search rankings.",
    )
    evidence = [
        Evidence.create(
            source_id=source.source_id,
            text=text,
            locator=EvidenceLocator(
                page_number=index, chunk_id=f"chunk-{index:016x}"
            ),
        )
        for index, text in enumerate(texts, start=1)
    ]
    return evidence


def test_sparse_bm25_prefers_matching_passage() -> None:
    evidence = _corpus()
    results = SparseRetriever(evidence).search("BM25 sparse lexical", limit=2)

    assert results[0].evidence == evidence[1]
    assert results[0].score > results[1].score
    assert results[0].sparse_rank == 1


def test_hashing_dense_fallback_is_local_and_deterministic() -> None:
    evidence = _corpus()
    first = DenseRetriever(evidence, embedder=HashingEmbedder(64)).search(
        "pgvector vector similarity", limit=2
    )
    second = DenseRetriever(evidence, embedder=HashingEmbedder(64)).search(
        "pgvector vector similarity", limit=2
    )

    assert first[0].evidence == evidence[0]
    assert [item.evidence.evidence_id for item in first] == [
        item.evidence.evidence_id for item in second
    ]


class _ControlledEmbedder:
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return [
            [1.0, 0.0] if "dense vector" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text: str) -> Sequence[float]:
        return [1.0, 0.0] if "semantic" in text else [0.0, 1.0]


def test_dense_interface_accepts_external_embedding_provider() -> None:
    evidence = _corpus()
    result = DenseRetriever(evidence, embedder=_ControlledEmbedder()).search(
        "semantic query", limit=1
    )

    assert result[0].evidence == evidence[0]
    assert result[0].dense_rank == 1


def test_rrf_rewards_passage_present_in_both_rankings() -> None:
    first, second, shared = _corpus()
    dense = [
        SearchResult(evidence=first, score=0.9, rank=1),
        SearchResult(evidence=shared, score=0.8, rank=2),
    ]
    sparse = [
        SearchResult(evidence=second, score=8.0, rank=1),
        SearchResult(evidence=shared, score=7.0, rank=2),
    ]

    fused = reciprocal_rank_fusion(dense, sparse, limit=3, rrf_k=10)

    assert fused[0].evidence == shared
    assert fused[0].dense_rank == fused[0].sparse_rank == 2
    assert len({result.evidence.evidence_id for result in fused}) == 3


def test_hybrid_search_exposes_component_diagnostics() -> None:
    evidence = _corpus()
    hybrid = HybridRetriever(
        DenseRetriever(evidence, embedder=HashingEmbedder(64)),
        SparseRetriever(evidence),
    )

    results = hybrid.search("dense sparse rank fusion", limit=2)

    assert results[0].evidence == evidence[2]
    assert results[0].dense_score is not None
    assert results[0].sparse_score is not None
    assert [result.rank for result in results] == [1, 2]
