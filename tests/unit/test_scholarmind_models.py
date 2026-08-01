"""Contracts for stable, source-grounded ScholarMind domain models."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from scholarmind.models import (
    Citation,
    Claim,
    ClaimStatus,
    Evidence,
    EvidenceLocator,
    Source,
    SourceKind,
)


def _domain_graph():
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Reliable Evidence Retrieval",
        uri="papers/reliable.pdf",
        content_sha256="a" * 64,
        paper_id="paper-0123456789abcdef",
        work_id="work-fedcba9876543210",
        identity="paper-0123456789abcdef",
    )
    locator = EvidenceLocator(
        page_number=3,
        section="4.2 Retrieval",
        bbox=(12.0, 24.0, 300.0, 420.0),
        chunk_id="chunk-0123456789abcdef",
        block_ids=("p3-b1", "p3-b2"),
    )
    evidence = Evidence.create(
        source_id=source.source_id,
        text="Hybrid retrieval combines dense and sparse rankings.",
        locator=locator,
        identity=locator.chunk_id,
    )
    claim = Claim.create(
        text="Hybrid retrieval combines dense and sparse rankings.",
        evidence_ids=[evidence.evidence_id],
        status=ClaimStatus.SUPPORTED,
        confidence=0.95,
    )
    citation = Citation.create(
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        source_id=source.source_id,
        locator=locator,
        label="p. 3",
    )
    return source, evidence, claim, citation


def test_stable_ids_and_json_round_trip() -> None:
    source, evidence, claim, citation = _domain_graph()
    repeated_source, repeated_evidence, repeated_claim, repeated_citation = _domain_graph()

    assert source.source_id == repeated_source.source_id
    assert evidence.evidence_id == repeated_evidence.evidence_id
    assert claim.claim_id == repeated_claim.claim_id
    assert citation.citation_id == repeated_citation.citation_id
    assert Source.model_validate_json(source.to_json()) == source
    assert Evidence.model_validate_json(evidence.to_json()) == evidence
    assert Claim.model_validate_json(claim.to_json()) == claim
    assert Citation.model_validate_json(citation.to_json()) == citation
    assert json.loads(citation.to_json())["locator"]["page_number"] == 3


def test_evidence_preserves_internal_newlines_and_validates_digest() -> None:
    source, _, _, _ = _domain_graph()
    text = "  First paragraph.\n\nSecond paragraph.  "
    final_text = text.strip()
    digest = hashlib.sha256(final_text.encode("utf-8")).hexdigest()

    evidence = Evidence.create(
        source_id=source.source_id,
        text=text,
        locator=EvidenceLocator(page_number=1),
        content_sha256=digest,
    )

    assert evidence.text == "First paragraph.\n\nSecond paragraph."
    assert evidence.content_sha256 == digest
    with pytest.raises(ValueError, match="does not match"):
        Evidence.create(
            source_id=source.source_id,
            text=text,
            locator=EvidenceLocator(page_number=1),
            content_sha256="0" * 64,
        )


def test_claim_identity_ignores_insignificant_whitespace_and_case() -> None:
    first = Claim.create(text="Vector search supports evidence retrieval.")
    second = Claim.create(text="  VECTOR   search supports evidence retrieval. ")

    assert first.claim_id == second.claim_id
    assert second.text == "VECTOR search supports evidence retrieval."


def test_supported_or_partial_claim_requires_evidence() -> None:
    for status in (ClaimStatus.SUPPORTED, ClaimStatus.PARTIAL):
        with pytest.raises(ValidationError, match="require evidence_ids"):
            Claim.create(text="Unsupported assertion", status=status)

    insufficient = Claim.create(
        text="No source establishes this statement.",
        status=ClaimStatus.INSUFFICIENT,
    )
    assert insufficient.evidence_ids == ()


def test_locator_rejects_invalid_page_range_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="page_end requires page_number"):
        EvidenceLocator(page_end=2)
    with pytest.raises(ValidationError, match="page_end cannot precede"):
        EvidenceLocator(page_number=4, page_end=3)
    with pytest.raises(ValidationError, match="Extra inputs"):
        EvidenceLocator(page_number=1, invented_location="x")


def test_models_are_frozen() -> None:
    source, _, _, _ = _domain_graph()
    with pytest.raises(ValidationError, match="frozen"):
        source.title = "Changed"  # type: ignore[misc]
