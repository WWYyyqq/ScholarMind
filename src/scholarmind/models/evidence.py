"""Verbatim evidence and its source locator."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import Field, field_validator, model_validator

from ._base import DomainModel, stable_id


class EvidenceLocator(DomainModel):
    """A machine-readable location that can be traced back to a source."""

    page_number: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    chunk_id: str | None = None
    block_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_page_range(self) -> EvidenceLocator:
        """Reject reversed page ranges."""
        if self.page_end is not None and self.page_number is None:
            raise ValueError("page_end requires page_number")
        if (
            self.page_end is not None
            and self.page_number is not None
            and self.page_end < self.page_number
        ):
            raise ValueError("page_end cannot precede page_number")
        return self

    @field_validator("block_ids")
    @classmethod
    def unique_blocks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Preserve reading order while removing duplicate block IDs."""
        return tuple(dict.fromkeys(value))


class Evidence(DomainModel):
    """A source-grounded passage suitable for supporting a claim."""

    evidence_id: str = Field(pattern=r"^evidence-[0-9a-f]{20}$")
    source_id: str = Field(pattern=r"^source-[0-9a-f]{20}$")
    text: str = Field(min_length=1)
    locator: EvidenceLocator
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        text: str,
        locator: EvidenceLocator,
        content_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
        identity: str | None = None,
    ) -> Evidence:
        """Build evidence whose identity remains stable across re-indexing."""
        canonical_text = text.strip()
        actual_digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        if content_sha256 is not None and content_sha256 != actual_digest:
            raise ValueError(
                "content_sha256 does not match the final evidence text"
            )
        digest = actual_digest
        canonical_identity = identity or locator.chunk_id or digest
        return cls(
            evidence_id=stable_id("evidence", source_id, canonical_identity),
            source_id=source_id,
            text=canonical_text,
            locator=locator,
            content_sha256=digest,
            metadata=metadata or {},
        )
