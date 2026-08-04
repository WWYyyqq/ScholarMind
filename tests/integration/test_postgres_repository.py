"""Real PostgreSQL/pgvector round-trip exercised by GitHub Actions."""

from __future__ import annotations

import os
from collections.abc import Sequence

import pytest

from scholarmind.models import (
    Citation,
    Claim,
    ClaimStatus,
    Evidence,
    EvidenceLocator,
    Source,
    SourceKind,
)
from scholarmind.retrieval import EvidenceIndexer
from scholarmind.storage import PostgresEvidenceRepository

DATABASE_DSN = os.getenv("SCHOLARMIND_TEST_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="SCHOLARMIND_TEST_DATABASE_DSN is not configured",
)


class _FixtureEmbedder:
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = {
            "The alpha model improves retrieval accuracy.": [1.0, 0.0],
            "The beta model reduces memory usage.": [0.0, 1.0],
        }
        return [vectors[text] for text in texts]

    def embed_query(self, text: str) -> Sequence[float]:
        return [1.0, 0.0] if "alpha" in text else [0.0, 1.0]


def test_postgres_pgvector_round_trip_and_dense_search() -> None:
    repository = PostgresEvidenceRepository.connect(str(DATABASE_DSN))
    try:
        repository.initialize_schema()
        source = Source.create(
            kind=SourceKind.PAPER,
            title="PostgreSQL integration fixture",
            uri="fixture://postgres-integration-paper",
        )
        first_locator = EvidenceLocator(page_number=2, chunk_id="integration-a")
        second_locator = EvidenceLocator(page_number=3, chunk_id="integration-b")
        first = Evidence.create(
            source_id=source.source_id,
            text="The alpha model improves retrieval accuracy.",
            locator=first_locator,
        )
        second = Evidence.create(
            source_id=source.source_id,
            text="The beta model reduces memory usage.",
            locator=second_locator,
        )
        claim = Claim.create(
            text=first.text,
            evidence_ids=[first.evidence_id],
            status=ClaimStatus.SUPPORTED,
            confidence=1.0,
        )
        citation = Citation.create(
            claim_id=claim.claim_id,
            evidence_id=first.evidence_id,
            source_id=source.source_id,
            locator=first.locator,
        )

        repository.upsert_sources((source,))
        repository.upsert_evidence_batch((first, second))
        repository.upsert_claim(claim)
        repository.upsert_citation(citation)
        indexing = EvidenceIndexer(
            _FixtureEmbedder(),
            model="fixture-v1",
            batch_size=1,
        ).index((first, second), repository)

        assert indexing.indexed_count == 2
        assert indexing.embedding_dimension == 2
        assert repository.list_embedding_ids(model="fixture-v1") == tuple(
            sorted((first.evidence_id, second.evidence_id))
        )
        assert repository.list_embedding_ids(model="missing-model") == ()

        assert repository.get_source(source.source_id) == source
        assert repository.get_evidence(first.evidence_id) == first
        assert repository.get_claim(claim.claim_id) == claim
        assert repository.get_citation(citation.citation_id) == citation
        assert repository.list_citations(claim_id=claim.claim_id) == (citation,)

        ranked = repository.dense_search(
            [1.0, 0.0],
            model="fixture-v1",
            limit=2,
        )
        assert [evidence.evidence_id for evidence, _ in ranked] == [
            first.evidence_id,
            second.evidence_id,
        ]
        assert ranked[0][1] == pytest.approx(1.0)

        changed_first = Evidence.create(
            source_id=source.source_id,
            text="The alpha model now contains revised evidence.",
            locator=first_locator,
        )
        assert changed_first.evidence_id == first.evidence_id
        repository.upsert_evidence_batch((changed_first,))

        assert repository.list_embedding_ids(model="fixture-v1") == (
            second.evidence_id,
        )
        fresh_only = repository.dense_search(
            [1.0, 0.0],
            model="fixture-v1",
            limit=2,
        )
        assert [item.evidence_id for item, _ in fresh_only] == [
            second.evidence_id
        ]
    finally:
        repository.close()
