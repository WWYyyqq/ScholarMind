from __future__ import annotations

from scholarmind.models import Claim, Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.researchers import ClaimDraft, FileResearcher, ResearchStatus
from scholarmind.retrieval import SearchResult
from scholarmind.verification import ClaimVerifier, VerificationStatus


def _fixture_evidence() -> tuple[Source, Evidence, Evidence]:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Citation precision study",
        uri="papers/citation-precision.pdf",
    )
    support = Evidence.create(
        source_id=source.source_id,
        text="The method improves accuracy by 12%.",
        locator=EvidenceLocator(page_number=4, chunk_id="chunk-support"),
    )
    distractor = Evidence.create(
        source_id=source.source_id,
        text="The appendix describes the hardware configuration.",
        locator=EvidenceLocator(page_number=9, chunk_id="chunk-distractor"),
    )
    return source, support, distractor


def test_one_unresolvable_link_makes_entire_claim_insufficient() -> None:
    _, support, _ = _fixture_evidence()
    missing_id = "evidence-00000000000000000000"
    claim = Claim.create(
        text="The method improves accuracy by 12%.",
        evidence_ids=(support.evidence_id, missing_id),
    )

    result = ClaimVerifier().verify(claim, [support])

    assert result.status is VerificationStatus.INSUFFICIENT
    assert not result.allows_publication
    assert missing_id in result.explanation


def test_verifier_returns_only_the_evidence_that_actually_supports_claim() -> None:
    _, support, distractor = _fixture_evidence()
    claim = Claim.create(
        text="The method improves accuracy by 12%.",
        evidence_ids=(distractor.evidence_id, support.evidence_id),
    )

    result = ClaimVerifier().verify(claim, [distractor, support])

    assert result.status is VerificationStatus.SUPPORTED
    assert result.evidence_ids == (support.evidence_id,)


class _Retriever:
    def __init__(self, evidence: tuple[Evidence, ...]) -> None:
        self.evidence = evidence

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        assert query
        return [
            SearchResult(evidence=item, score=1.0 / rank, rank=rank)
            for rank, item in enumerate(self.evidence[:limit], start=1)
        ]


class _MultiEvidenceDraft:
    def __init__(self, evidence_ids: tuple[str, ...]) -> None:
        self.evidence_ids = evidence_ids

    def generate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
    ) -> list[ClaimDraft]:
        assert question and evidence
        return [
            ClaimDraft(
                "The method improves accuracy by 12%.",
                self.evidence_ids,
            )
        ]


def test_file_report_cites_supporting_page_not_every_retrieved_page() -> None:
    source, support, distractor = _fixture_evidence()
    researcher = FileResearcher(
        _Retriever((distractor, support)),
        claim_generator=_MultiEvidenceDraft(
            (distractor.evidence_id, support.evidence_id)
        ),
        sources={source.source_id: source},
    )

    result = researcher.research("What accuracy gain is reported?")

    assert result.status is ResearchStatus.SUCCESS
    assert result.published_claims[0].evidence_ids == (support.evidence_id,)
    assert len(result.citations) == 1
    assert result.citations[0].evidence_id == support.evidence_id
    assert result.citations[0].locator.page_number == 4
    assert result.report is not None
    assert "p. 4" in result.report
    assert "p. 9" not in result.report
