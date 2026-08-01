from __future__ import annotations

from scholarmind.models import Claim, Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.verification import ClaimVerifier, VerificationStatus


def test_reversed_comparison_is_not_supported_despite_full_token_overlap() -> None:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Comparison study",
        uri="papers/comparison.pdf",
    )
    evidence = Evidence.create(
        source_id=source.source_id,
        text="Model B outperforms Model A.",
        locator=EvidenceLocator(page_number=5, chunk_id="chunk-comparison"),
    )
    claim = Claim.create(
        text="Model A outperforms Model B.",
        evidence_ids=(evidence.evidence_id,),
    )

    result = ClaimVerifier().verify(claim, [evidence])

    assert result.coverage == 1.0
    assert result.status is VerificationStatus.PARTIAL
    assert not result.allows_publication
    assert "strict extractive match" in result.explanation
