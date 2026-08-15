from __future__ import annotations

from scholarmind.models import (
    ClaimStatus,
    Evidence,
    EvidenceLocator,
    Source,
    SourceKind,
)
from scholarmind.researchers import (
    ClaimDraft,
    ExtractiveClaimGenerator,
    FileResearcher,
    ResearchStatus,
)
from scholarmind.retrieval import SearchResult


class _Retriever:
    def __init__(
        self,
        evidence: list[Evidence],
        *,
        error: Exception | None = None,
    ) -> None:
        self.evidence = evidence
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return [
            SearchResult(evidence=item, score=1.0 / rank, rank=rank)
            for rank, item in enumerate(self.evidence[:limit], start=1)
        ]


class _DraftGenerator:
    def __init__(self, drafts: list[ClaimDraft]) -> None:
        self.drafts = drafts

    def generate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
    ) -> list[ClaimDraft]:
        assert question
        assert evidence
        return self.drafts


def _source() -> Source:
    return Source.create(
        kind=SourceKind.PAPER,
        title="Synthetic retrieval study",
        uri="file:///papers/synthetic.pdf",
    )


def _evidence(
    source: Source,
    *,
    text: str = "The method improves accuracy by 12%.",
    page: int | None = 3,
) -> Evidence:
    return Evidence.create(
        source_id=source.source_id,
        text=text,
        locator=EvidenceLocator(
            page_number=page,
            section="Results",
            chunk_id=f"chunk-page-{page}",
        ),
    )


def test_local_retrieval_produces_evidence_claim_citation_and_page_report() -> None:
    source = _source()
    evidence = _evidence(
        source,
        text=(
            "The method improves accuracy by 12%. "
            "This second sentence must not be invented into the first claim."
        ),
    )
    retriever = _Retriever([evidence])
    researcher = FileResearcher(
        retriever,
        sources={source.source_id: source},
        top_k=3,
    )

    result = researcher.research("  How much does the method improve accuracy?  ")

    assert retriever.calls == [("How much does the method improve accuracy?", 3)]
    assert result.status is ResearchStatus.SUCCESS
    assert result.publication_ready
    assert result.source_ids == (source.source_id,)
    assert len(result.evidence) == 1
    assert len(result.published_claims) == 1
    assert result.published_claims[0].evidence_ids == (evidence.evidence_id,)
    assert len(result.citations) == 1
    assert result.citations[0].locator.page_number == 3
    assert result.citations[0].label == "[Synthetic retrieval study, p. 3]"
    assert result.report is not None
    assert "The method improves accuracy by 12%." in result.report
    assert "[Synthetic retrieval study, p. 3]" in result.report
    assert "second sentence" not in result.report


def test_extractive_generator_selects_question_relevant_sentence() -> None:
    source = _source()
    evidence = _evidence(
        source,
        text=(
            "The appendix lists implementation details for reproducibility. "
            "The anomaly detection model uses channel attention to identify "
            "sensitive metrics."
        ),
    )

    drafts = ExtractiveClaimGenerator().generate(
        "Which model improves anomaly detection?",
        (evidence,),
    )

    assert len(drafts) == 1
    assert drafts[0].text.startswith("The anomaly detection model")
    assert drafts[0].metadata["generator"] == "extractive-query-aware"


def test_extractive_generator_skips_reference_and_heading_fragments() -> None:
    source = _source()
    evidence = _evidence(
        source,
        text=(
            "III. "
            "[67] Y. Su et al. Robust anomaly detection, in Proceedings of "
            "KDD 2019. "
            "Lyu, “Heterogeneous anomaly detection via cross-modal "
            "attention,” 2022. "
            "between hard and abnormal samples, reduce false positives, "
            "and improve anomaly detection. "
            "Metrics are standardized before the root cause localization "
            "model analyzes dependencies between services."
        ),
    )

    drafts = ExtractiveClaimGenerator().generate(
        "How does the root cause localization model process metrics?",
        (evidence,),
    )

    assert len(drafts) == 1
    assert drafts[0].text.startswith("Metrics are standardized")


def test_extractive_generator_skips_truncated_sentence_at_chunk_boundary() -> None:
    source = _source()
    evidence = _evidence(
        source,
        text=(
            "The dependency graph then propagates anomaly scores to rank "
            "candidate root causes. "
            "Random-walk methods rank likely root causes because frequently "
            "visited services are more likely to have caused the observed"
        ),
    )

    drafts = ExtractiveClaimGenerator().generate(
        "How does a dependency graph rank root causes?",
        (evidence,),
    )

    assert len(drafts) == 1
    assert drafts[0].text == (
        "The dependency graph then propagates anomaly scores to rank "
        "candidate root causes."
    )


def test_no_page_located_evidence_blocks_report_generation() -> None:
    source = _source()
    unlocated = _evidence(source, page=None)

    result = FileResearcher(_Retriever([unlocated])).research("What changed?")

    assert result.status is ResearchStatus.FAILED
    assert not result.publication_ready
    assert result.report is None
    assert result.claims == ()
    assert result.citations == ()
    assert result.errors == ("No page-located local evidence was retrieved.",)


def test_unsupported_claim_cannot_be_rendered_as_successful_report() -> None:
    source = _source()
    evidence = _evidence(source)
    generator = _DraftGenerator(
        [
            ClaimDraft(
                text="The method improves accuracy by 99%.",
                evidence_ids=(evidence.evidence_id,),
            )
        ]
    )

    result = FileResearcher(
        _Retriever([evidence]),
        claim_generator=generator,
    ).research("How much does accuracy improve?")

    assert result.status is ResearchStatus.FAILED
    assert result.report is None
    assert result.citations == ()
    assert len(result.rejected_claims) == 1
    assert result.rejected_claims[0].status is ClaimStatus.CONTRADICTED
    assert "All candidate claims failed" in result.errors[0]


def test_partial_run_publishes_only_fully_supported_claims() -> None:
    source = _source()
    evidence = _evidence(source)
    supported_text = "The method improves accuracy by 12%."
    contradicted_text = "The method improves accuracy by 99%."
    generator = _DraftGenerator(
        [
            ClaimDraft(supported_text, (evidence.evidence_id,)),
            ClaimDraft(contradicted_text, (evidence.evidence_id,)),
        ]
    )

    result = FileResearcher(
        _Retriever([evidence]),
        claim_generator=generator,
    ).research("Summarize the result.")

    assert result.status is ResearchStatus.PARTIAL
    assert result.publication_ready
    assert len(result.published_claims) == 1
    assert len(result.rejected_claims) == 1
    assert result.report is not None
    assert supported_text in result.report
    assert contradicted_text not in result.report
    assert len(result.citations) == 1


def test_retrieval_exception_becomes_structured_failure() -> None:
    result = FileResearcher(
        _Retriever([], error=RuntimeError("index unavailable"))
    ).research("What changed?")

    assert result.status is ResearchStatus.FAILED
    assert result.report is None
    assert result.errors == (
        "Retrieval failed: RuntimeError: index unavailable",
    )
