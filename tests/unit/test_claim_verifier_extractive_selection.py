from __future__ import annotations

from scholarmind.models import Claim, Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.verification import ClaimVerifier, VerificationStatus


def test_any_linked_exact_sentence_wins_over_shorter_reversed_sentence() -> None:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Multi-evidence comparison",
        uri="papers/multi-evidence.pdf",
    )
    reversed_evidence = Evidence.create(
        source_id=source.source_id,
        text="Model B outperforms Model A.",
        locator=EvidenceLocator(page_number=2, chunk_id="chunk-reversed"),
    )
    supporting_evidence = Evidence.create(
        source_id=source.source_id,
        text="In the benchmark, Model A outperforms Model B.",
        locator=EvidenceLocator(page_number=8, chunk_id="chunk-supporting"),
    )
    claim = Claim.create(
        text="Model A outperforms Model B.",
        evidence_ids=(reversed_evidence.evidence_id, supporting_evidence.evidence_id),
    )

    result = ClaimVerifier().verify(
        claim,
        [reversed_evidence, supporting_evidence],
    )

    assert result.status is VerificationStatus.SUPPORTED
    assert result.evidence_ids == (supporting_evidence.evidence_id,)
