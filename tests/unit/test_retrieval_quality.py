"""Tests for explainable quality filtering and local reranking."""

from __future__ import annotations

from scholarmind.models import Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.retrieval import (
    EvidenceQualityPolicy,
    OpenAIRerankProvider,
    QualityFilteredRetriever,
    RerankingRetriever,
    SearchResult,
)


def _evidence(*, text: str, section: str, chunk_id: str) -> Evidence:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Quality fixture",
        uri="fixture://quality-paper",
    )
    return Evidence.create(
        source_id=source.source_id,
        text=text,
        locator=EvidenceLocator(
            page_number=3,
            section=section,
            chunk_id=chunk_id,
        ),
    )


class _StaticRetriever:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.requested_limits: list[int] = []

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        self.requested_limits.append(limit)
        return self.results[:limit]


def test_quality_policy_rejects_short_heading_and_reference_section() -> None:
    policy = EvidenceQualityPolicy()
    heading = _evidence(
        text="2.3.1 Time Series Anomaly Detection",
        section="Related Work",
        chunk_id="chunk-heading",
    )
    bibliography = _evidence(
        text=(
            "This bibliography passage is deliberately long enough to avoid "
            "being rejected only because of its character count."
        ),
        section="References",
        chunk_id="chunk-reference",
    )

    heading_assessment = policy.assess(heading)
    reference_assessment = policy.assess(bibliography)

    assert not heading_assessment.accepted
    assert "too_short" in heading_assessment.reasons
    assert "heading_only" in heading_assessment.reasons
    assert not reference_assessment.accepted
    assert "reference_section" in reference_assessment.reasons


def test_quality_policy_rejects_spilled_reference_list_without_section_label() -> None:
    policy = EvidenceQualityPolicy()
    reference_list = _evidence(
        text=(
            "Symposium proceedings, pages 1-9. "
            "[74] Ruyue Xin and Peng Chen. 2023. Causal root cause "
            "localization for microservices. Journal of Systems. "
            "[75] Xiang Xuan and Kevin Murphy. 2007. Modeling changing "
            "dependency structure in multivariate time series."
        ),
        section="document",
        chunk_id="chunk-spilled-references",
    )

    assessment = policy.assess(reference_list)

    assert not assessment.accepted
    assert "reference_list" in assessment.reasons


def test_quality_filter_overfetches_and_preserves_substantive_evidence() -> None:
    noise = _evidence(
        text="2.3.1 Time Series Anomaly Detection",
        section="Related Work",
        chunk_id="chunk-noise",
    )
    substantive = _evidence(
        text=(
            "The proposed graph attention model captures dependencies between "
            "multiple sensors and improves multivariate anomaly detection."
        ),
        section="Method",
        chunk_id="chunk-substantive",
    )
    base = _StaticRetriever(
        [
            SearchResult(evidence=noise, score=0.9, rank=1),
            SearchResult(evidence=substantive, score=0.8, rank=2),
        ]
    )

    results = QualityFilteredRetriever(
        base,
        candidate_multiplier=2,
    ).search("multivariate anomaly detection", limit=1)

    assert base.requested_limits == [2]
    assert [result.evidence for result in results] == [substantive]
    assert results[0].rank == 1
    assert results[0].quality_score is not None


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.2},
            ]
        }


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, endpoint: str, *, json: dict[str, object]) -> _FakeResponse:
        self.calls.append((endpoint, json))
        return _FakeResponse()


def test_openai_rerank_provider_restores_input_order() -> None:
    client = _FakeHttpClient()
    provider = OpenAIRerankProvider(
        model="qwen3-embedding-local",
        base_url="http://[::1]:8001/v1/",
        client=client,
    )

    scores = provider.score(
        " anomaly   detection ",
        [" first  document ", "second\ndocument"],
    )

    assert scores == (0.2, 0.9)
    endpoint, payload = client.calls[0]
    assert endpoint == "http://[::1]:8001/rerank"
    assert payload["query"] == "anomaly detection"
    assert payload["documents"] == ["first document", "second document"]
    assert payload["top_n"] == 2


class _ControlledReranker:
    def score(self, query: str, documents: list[str]) -> tuple[float, ...]:
        assert query == "root cause analysis"
        assert len(documents) == 2
        return 0.1, 0.95


def test_reranking_reorders_candidates_and_preserves_diagnostics() -> None:
    first = _evidence(
        text=(
            "A generic anomaly detector identifies unusual observations in a "
            "multivariate monitoring stream."
        ),
        section="Background",
        chunk_id="chunk-first",
    )
    second = _evidence(
        text=(
            "The causal dependency graph localizes the root cause after a "
            "multivariate time-series anomaly is detected."
        ),
        section="Method",
        chunk_id="chunk-second",
    )
    base = _StaticRetriever(
        [
            SearchResult(
                evidence=first,
                score=0.03,
                rank=1,
                dense_score=0.8,
                quality_score=0.9,
            ),
            SearchResult(
                evidence=second,
                score=0.02,
                rank=2,
                sparse_score=4.0,
                quality_score=1.0,
            ),
        ]
    )

    results = RerankingRetriever(
        base,
        reranker=_ControlledReranker(),
        candidate_multiplier=2,
    ).search("root cause analysis", limit=1)

    assert base.requested_limits == [2]
    assert results[0].evidence == second
    assert results[0].rank == 1
    assert results[0].score == results[0].reranker_score == 0.95
    assert results[0].sparse_score == 4.0
    assert results[0].quality_score == 1.0
