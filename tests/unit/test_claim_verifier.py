from __future__ import annotations

import pytest

from scholarmind.models import Claim, Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.verification import ClaimVerifier, VerificationStatus


def _evidence(text: str = "The method improves accuracy by 12%.") -> Evidence:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Synthetic retrieval study",
        uri="file:///papers/synthetic.pdf",
    )
    return Evidence.create(
        source_id=source.source_id,
        text=text,
        locator=EvidenceLocator(page_number=3, chunk_id="chunk-test"),
    )


def _claim(text: str, evidence_ids: tuple[str, ...]) -> Claim:
    return Claim.create(text=text, evidence_ids=evidence_ids)


def test_supported_claim_requires_linked_evidence_and_full_material_coverage() -> None:
    evidence = _evidence(
        "The method improves accuracy by 12%. The experiment uses three datasets."
    )
    claim = _claim(
        "The method improves accuracy by 12%.",
        (evidence.evidence_id,),
    )

    result = ClaimVerifier().verify(claim, [evidence])

    assert result.status is VerificationStatus.SUPPORTED
    assert result.allows_publication
    assert result.evidence_ids == (evidence.evidence_id,)
    assert result.coverage == 1.0


def test_partially_supported_overstatement_is_not_publishable() -> None:
    evidence = _evidence()
    claim = _claim(
        "The method improves accuracy by 12% on unseen external hospitals.",
        (evidence.evidence_id,),
    )

    result = ClaimVerifier().verify(claim, [evidence])

    assert result.status is VerificationStatus.PARTIAL
    assert not result.allows_publication
    assert 0.45 <= result.coverage < 0.8


def test_conflicting_number_is_contradicted() -> None:
    evidence = _evidence()
    claim = _claim(
        "The method improves accuracy by 99%.",
        (evidence.evidence_id,),
    )

    result = ClaimVerifier().verify(claim, [evidence])

    assert result.status is VerificationStatus.CONTRADICTED
    assert "99%" in result.explanation
    assert not result.allows_publication


def test_conflicting_polarity_is_contradicted() -> None:
    evidence = _evidence("The method does not improve accuracy.")
    claim = _claim(
        "The method improves accuracy.",
        (evidence.evidence_id,),
    )

    result = ClaimVerifier().verify(claim, [evidence])

    assert result.status is VerificationStatus.CONTRADICTED
    assert "polarity" in result.explanation


@pytest.mark.parametrize(
    "evidence_ids,available",
    [
        ((), []),
        (("evidence-00000000000000000000",), []),
    ],
)
def test_missing_or_unresolvable_evidence_is_insufficient(
    evidence_ids: tuple[str, ...],
    available: list[Evidence],
) -> None:
    claim = _claim("The method improves accuracy.", evidence_ids)

    result = ClaimVerifier().verify(claim, available)

    assert result.status is VerificationStatus.INSUFFICIENT
    assert not result.allows_publication


def test_threshold_order_is_validated() -> None:
    with pytest.raises(ValueError, match="partial <= supported"):
        ClaimVerifier(supported_threshold=0.4, partial_threshold=0.5)
