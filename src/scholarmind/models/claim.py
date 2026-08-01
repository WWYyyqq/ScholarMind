"""Claims and their explicit evidence relationships."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from ._base import DomainModel, normalize_text, stable_id


class ClaimStatus(str, Enum):
    """Verification state assigned by an evidence verifier."""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    PARTIAL = "partial"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


class Claim(DomainModel):
    """A factual statement linked to zero or more evidence passages."""

    claim_id: str = Field(pattern=r"^claim-[0-9a-f]{20}$")
    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Validate relationship IDs and remove duplicates in input order."""
        unique = tuple(dict.fromkeys(value))
        if any(
            not evidence_id.startswith("evidence-") or len(evidence_id) != 29
            for evidence_id in unique
        ):
            raise ValueError("evidence_ids must contain ScholarMind evidence IDs")
        return unique

    @model_validator(mode="after")
    def supported_claim_requires_evidence(self) -> Claim:
        """Prevent declaring support without at least one cited passage."""
        if self.status in {ClaimStatus.SUPPORTED, ClaimStatus.PARTIAL} and not self.evidence_ids:
            raise ValueError(f"{self.status.value} claims require evidence_ids")
        return self

    @classmethod
    def create(
        cls,
        *,
        text: str,
        evidence_ids: tuple[str, ...] | list[str] = (),
        status: ClaimStatus | str = ClaimStatus.UNVERIFIED,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
        identity: str | None = None,
    ) -> Claim:
        """Build a claim with identity based on normalized statement text."""
        canonical_text = normalize_text(text)
        return cls(
            claim_id=stable_id("claim", identity or canonical_text.casefold()),
            text=canonical_text,
            evidence_ids=tuple(evidence_ids),
            status=status,
            confidence=confidence,
            metadata=metadata or {},
        )
