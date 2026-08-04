"""Repository contracts independent of a database driver."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..models import Citation, Claim, Evidence, Source


class RepositoryIntegrityError(ValueError):
    """Raised when a persisted domain relationship would be invalid."""


class EvidenceRepository(Protocol):
    """Minimal persistence port used by ingestion and research workflows."""

    def upsert_source(self, source: Source) -> None:
        """Insert or replace a source by stable ID."""
        ...

    def upsert_evidence(self, evidence: Evidence) -> None:
        """Insert or replace evidence after validating its source."""
        ...

    def upsert_claim(self, claim: Claim) -> None:
        """Insert or replace a claim after validating evidence links."""
        ...

    def upsert_citation(self, citation: Citation) -> None:
        """Insert or replace a validated claim/evidence citation edge."""
        ...

    def get_source(self, source_id: str) -> Source | None:
        """Return a source by ID."""
        ...

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Return evidence by ID."""
        ...

    def get_claim(self, claim_id: str) -> Claim | None:
        """Return a claim by ID."""
        ...

    def get_citation(self, citation_id: str) -> Citation | None:
        """Return a citation by ID."""
        ...

    def list_sources(self) -> tuple[Source, ...]:
        """Return sources in stable ID order."""
        ...

    def list_evidence(self, *, source_id: str | None = None) -> tuple[Evidence, ...]:
        """Return all evidence, optionally constrained to one source."""
        ...

    def list_claims(self) -> tuple[Claim, ...]:
        """Return claims in stable ID order."""
        ...

    def list_citations(self, *, claim_id: str | None = None) -> tuple[Citation, ...]:
        """Return citations, optionally constrained to one claim."""
        ...

class EmbeddingRepository(Protocol):
    """Persistence port required by the batch evidence indexer."""

    def list_embedding_ids(self, *, model: str) -> tuple[str, ...]:
        """Return evidence IDs already embedded by one model."""
        ...

    def upsert_embedding(
        self, evidence_id: str, embedding: Sequence[float], *, model: str
    ) -> None:
        """Insert or replace one model-qualified evidence vector."""
        ...


class VectorEvidenceRepository(
    EvidenceRepository, EmbeddingRepository, Protocol
):
    """Repository supporting both evidence entities and their embeddings."""
