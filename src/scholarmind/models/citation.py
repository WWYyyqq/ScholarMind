"""Claim-to-evidence citation edges."""

from __future__ import annotations

from pydantic import Field

from ._base import DomainModel, stable_id
from .evidence import EvidenceLocator


class Citation(DomainModel):
    """An auditable edge from one claim to one evidence passage."""

    citation_id: str = Field(pattern=r"^citation-[0-9a-f]{20}$")
    claim_id: str = Field(pattern=r"^claim-[0-9a-f]{20}$")
    evidence_id: str = Field(pattern=r"^evidence-[0-9a-f]{20}$")
    source_id: str = Field(pattern=r"^source-[0-9a-f]{20}$")
    locator: EvidenceLocator
    label: str | None = None

    @classmethod
    def create(
        cls,
        *,
        claim_id: str,
        evidence_id: str,
        source_id: str,
        locator: EvidenceLocator,
        label: str | None = None,
    ) -> Citation:
        """Build a stable citation edge for a claim/evidence pair."""
        return cls(
            citation_id=stable_id("citation", claim_id, evidence_id),
            claim_id=claim_id,
            evidence_id=evidence_id,
            source_id=source_id,
            locator=locator,
            label=label,
        )
