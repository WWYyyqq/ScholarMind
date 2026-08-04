"""Thread-safe in-memory repository for tests and zero-service local runs."""

from __future__ import annotations

from threading import RLock

from ..models import Citation, Claim, Evidence, Source
from .repository import RepositoryIntegrityError


class InMemoryEvidenceRepository:
    """A deterministic repository with the same relationship checks as SQL storage."""

    def __init__(self) -> None:
        """Create empty thread-safe entity maps."""
        self._sources: dict[str, Source] = {}
        self._evidence: dict[str, Evidence] = {}
        self._claims: dict[str, Claim] = {}
        self._citations: dict[str, Citation] = {}
        self._lock = RLock()

    def upsert_source(self, source: Source) -> None:
        """Insert or replace a source by stable ID."""
        with self._lock:
            self._sources[source.source_id] = source

    def upsert_evidence(self, evidence: Evidence) -> None:
        """Persist evidence only after its source is present."""
        with self._lock:
            if evidence.source_id not in self._sources:
                raise RepositoryIntegrityError(
                    f"unknown source_id {evidence.source_id!r} for evidence"
                )
            self._evidence[evidence.evidence_id] = evidence

    def upsert_claim(self, claim: Claim) -> None:
        """Persist a claim only when every evidence relationship resolves."""
        with self._lock:
            missing = sorted(
                evidence_id
                for evidence_id in claim.evidence_ids
                if evidence_id not in self._evidence
            )
            if missing:
                raise RepositoryIntegrityError(
                    f"claim references unknown evidence_ids: {', '.join(missing)}"
                )
            self._claims[claim.claim_id] = claim

    def upsert_citation(self, citation: Citation) -> None:
        """Persist an edge only when claim, evidence, and source agree."""
        with self._lock:
            claim = self._claims.get(citation.claim_id)
            evidence = self._evidence.get(citation.evidence_id)
            source = self._sources.get(citation.source_id)
            if claim is None:
                raise RepositoryIntegrityError(
                    f"unknown claim_id {citation.claim_id!r} for citation"
                )
            if evidence is None:
                raise RepositoryIntegrityError(
                    f"unknown evidence_id {citation.evidence_id!r} for citation"
                )
            if source is None:
                raise RepositoryIntegrityError(
                    f"unknown source_id {citation.source_id!r} for citation"
                )
            if citation.evidence_id not in claim.evidence_ids:
                raise RepositoryIntegrityError(
                    "citation evidence_id is not linked by the referenced claim"
                )
            if evidence.source_id != citation.source_id:
                raise RepositoryIntegrityError(
                    "citation source_id does not own the referenced evidence"
                )
            if evidence.locator != citation.locator:
                raise RepositoryIntegrityError(
                    "citation locator does not match the referenced evidence"
                )
            self._citations[citation.citation_id] = citation

    def get_source(self, source_id: str) -> Source | None:
        """Return a source by ID."""
        with self._lock:
            return self._sources.get(source_id)

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Return evidence by ID."""
        with self._lock:
            return self._evidence.get(evidence_id)

    def get_claim(self, claim_id: str) -> Claim | None:
        """Return a claim by ID."""
        with self._lock:
            return self._claims.get(claim_id)

    def get_citation(self, citation_id: str) -> Citation | None:
        """Return a citation by ID."""
        with self._lock:
            return self._citations.get(citation_id)

    def list_sources(self) -> tuple[Source, ...]:
        """Return sources in stable ID order."""
        with self._lock:
            return tuple(self._sources[key] for key in sorted(self._sources))

    def list_evidence(self, *, source_id: str | None = None) -> tuple[Evidence, ...]:
        """Return evidence in stable ID order with an optional source filter."""
        with self._lock:
            return tuple(
                self._evidence[key]
                for key in sorted(self._evidence)
                if source_id is None or self._evidence[key].source_id == source_id
            )

    def list_claims(self) -> tuple[Claim, ...]:
        """Return claims in stable ID order."""
        with self._lock:
            return tuple(self._claims[key] for key in sorted(self._claims))

    def list_citations(self, *, claim_id: str | None = None) -> tuple[Citation, ...]:
        """Return citations in stable ID order with an optional claim filter."""
        with self._lock:
            return tuple(
                self._citations[key]
                for key in sorted(self._citations)
                if claim_id is None or self._citations[key].claim_id == claim_id
            )
