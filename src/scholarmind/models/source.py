"""Source aggregate root."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from ._base import DomainModel, normalize_text, stable_id

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SourceKind(str, Enum):
    """Supported provenance types."""

    PAPER = "paper"
    WEB = "web"
    FILE = "file"
    DATASET = "dataset"
    OTHER = "other"


class Source(DomainModel):
    """A uniquely identifiable document or external information source."""

    source_id: str = Field(pattern=r"^source-[0-9a-f]{20}$")
    kind: SourceKind
    title: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    content_sha256: str | None = None
    paper_id: str | None = None
    work_id: str | None = None
    language: str = "unknown"
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        """Require a lowercase hexadecimal SHA-256 when supplied."""
        if value is not None and not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("content_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Remove empty and duplicate source aliases deterministically."""
        return tuple(dict.fromkeys(alias.strip() for alias in value if alias.strip()))

    @classmethod
    def create(
        cls,
        *,
        kind: SourceKind | str,
        title: str,
        uri: str,
        content_sha256: str | None = None,
        paper_id: str | None = None,
        work_id: str | None = None,
        language: str = "unknown",
        aliases: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
        identity: str | None = None,
    ) -> Source:
        """Build a source with an ID stable across repeated ingestion runs."""
        canonical_uri = uri.strip()
        canonical_identity = identity or content_sha256 or canonical_uri
        return cls(
            source_id=stable_id("source", canonical_identity),
            kind=kind,
            title=normalize_text(title),
            uri=canonical_uri,
            content_sha256=content_sha256,
            paper_id=paper_id,
            work_id=work_id,
            language=language,
            aliases=tuple(aliases),
            metadata=metadata or {},
        )
