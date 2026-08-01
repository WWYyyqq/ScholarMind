from __future__ import annotations

from typing import Any

from scholarmind.models import Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.researchers import ClaimDraft, FileResearcher, ResearchStatus
from scholarmind.retrieval import SearchResult
from scholarmind.verification import ClaimVerifier


class _Retriever:
    def __init__(self, results: list[Any]) -> None:
        self.results = results

    def search(self, query: str, *, limit: int = 5) -> list[Any]:
        assert query
        return self.results[:limit]


class _Generator:
    def __init__(self, drafts: list[ClaimDraft]) -> None:
        self.drafts = drafts

    def generate(
        self,
        question: str,
        evidence: tuple[Evidence, ...],
    ) -> list[ClaimDraft]:
        assert question and evidence
        return self.drafts


class _SelectiveVerifier:
    def __init__(self, failing_text: str) -> None:
        self.failing_text = failing_text
        self.delegate = ClaimVerifier()

    def verify(self, claim, evidence):
        if claim.text == self.failing_text:
            raise RuntimeError("verification backend unavailable")
        return self.delegate.verify(claim, evidence)


class _CitationFailingResearcher(FileResearcher):
    def _citation_label(self, evidence: Evidence) -> str:
        if evidence.locator.page_number == 9:
            raise RuntimeError("citation renderer unavailable")
        return super()._citation_label(evidence)


def _fixtures() -> tuple[Source, Evidence, Evidence]:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Failure isolation study",
        uri="papers/failure-isolation.pdf",
    )
    healthy = Evidence.create(
        source_id=source.source_id,
        text="The healthy method improves accuracy.",
        locator=EvidenceLocator(page_number=4, chunk_id="chunk-healthy"),
    )
    secondary = Evidence.create(
        source_id=source.source_id,
        text="The secondary method reduces latency.",
        locator=EvidenceLocator(page_number=9, chunk_id="chunk-secondary"),
    )
    return source, healthy, secondary


def _hit(evidence: Evidence, rank: int) -> SearchResult:
    return SearchResult(evidence=evidence, score=1.0 / rank, rank=rank)


def test_malformed_hit_isolated_while_valid_hit_still_publishes() -> None:
    source, healthy, _ = _fixtures()
    researcher = FileResearcher(
        _Retriever([object(), _hit(healthy, 2)]),
        sources={source.source_id: source},
    )

    result = researcher.research("What improves accuracy?")

    assert result.status is ResearchStatus.PARTIAL
    assert result.publication_ready
    assert result.evidence == (healthy,)
    assert len(result.published_claims) == 1
    assert "Search hit 1 was ignored" in result.errors[0]


def test_invalid_claim_draft_does_not_discard_healthy_claim() -> None:
    source, healthy, _ = _fixtures()
    generator = _Generator(
        [
            ClaimDraft("", (healthy.evidence_id,)),
            ClaimDraft(healthy.text, (healthy.evidence_id,)),
        ]
    )
    researcher = FileResearcher(
        _Retriever([_hit(healthy, 1)]),
        claim_generator=generator,
        sources={source.source_id: source},
    )

    result = researcher.research("What improves accuracy?")

    assert result.status is ResearchStatus.PARTIAL
    assert result.publication_ready
    assert len(result.published_claims) == 1
    assert any("Claim draft 1 was rejected" in error for error in result.errors)


def test_verifier_exception_isolated_per_claim() -> None:
    source, healthy, secondary = _fixtures()
    generator = _Generator(
        [
            ClaimDraft(healthy.text, (healthy.evidence_id,)),
            ClaimDraft(secondary.text, (secondary.evidence_id,)),
        ]
    )
    researcher = FileResearcher(
        _Retriever([_hit(healthy, 1), _hit(secondary, 2)]),
        claim_generator=generator,
        verifier=_SelectiveVerifier(secondary.text),
        sources={source.source_id: source},
    )

    result = researcher.research("Compare both methods.")

    assert result.status is ResearchStatus.PARTIAL
    assert result.publication_ready
    assert len(result.published_claims) == 1
    assert len(result.rejected_claims) == 1
    assert any("verification failed" in error for error in result.errors)
    assert result.report is not None and healthy.text in result.report
    assert secondary.text not in result.report


def test_citation_exception_rejects_only_affected_claim() -> None:
    source, healthy, secondary = _fixtures()
    generator = _Generator(
        [
            ClaimDraft(healthy.text, (healthy.evidence_id,)),
            ClaimDraft(secondary.text, (secondary.evidence_id,)),
        ]
    )
    researcher = _CitationFailingResearcher(
        _Retriever([_hit(healthy, 1), _hit(secondary, 2)]),
        claim_generator=generator,
        sources={source.source_id: source},
    )

    result = researcher.research("Compare both methods.")

    assert result.status is ResearchStatus.PARTIAL
    assert result.publication_ready
    assert len(result.published_claims) == 1
    assert len(result.citations) == 1
    assert result.citations[0].evidence_id == healthy.evidence_id
    assert any("citation failed" in error for error in result.errors)
    assert result.report is not None and "p. 4" in result.report
    assert "p. 9" not in result.report


def test_all_invalid_claim_drafts_return_structured_failure() -> None:
    _, healthy, _ = _fixtures()
    researcher = FileResearcher(
        _Retriever([_hit(healthy, 1)]),
        claim_generator=_Generator([ClaimDraft("", (healthy.evidence_id,))]),
    )

    result = researcher.research("What improves accuracy?")

    assert result.status is ResearchStatus.FAILED
    assert not result.publication_ready
    assert result.report is None
    assert any("Claim draft 1 was rejected" in error for error in result.errors)
    assert result.errors[-1] == "All candidate claims failed the evidence gate."
