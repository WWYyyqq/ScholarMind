"""Repository tests for deduplication and relationship integrity."""

import sys
from pathlib import Path
from types import SimpleNamespace

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
from scholarmind.storage import InMemoryEvidenceRepository, RepositoryIntegrityError
from scholarmind.storage.postgres import PostgresEvidenceRepository


def _entities():
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Repository Contract",
        uri="papers/repository.pdf",
        identity="repository-paper",
    )
    locator = EvidenceLocator(page_number=2, chunk_id="chunk-fedcba9876543210")
    evidence = Evidence.create(
        source_id=source.source_id,
        text="The repository enforces provenance relationships.",
        locator=locator,
    )
    claim = Claim.create(
        text="The repository enforces provenance relationships.",
        evidence_ids=[evidence.evidence_id],
        status=ClaimStatus.SUPPORTED,
        confidence=1.0,
    )
    citation = Citation.create(
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        source_id=source.source_id,
        locator=locator,
    )
    return source, evidence, claim, citation


def test_idempotent_upserts_deduplicate_entities() -> None:
    repository = InMemoryEvidenceRepository()
    source, evidence, claim, citation = _entities()
    for _ in range(2):
        repository.upsert_source(source)
        repository.upsert_evidence(evidence)
        repository.upsert_claim(claim)
        repository.upsert_citation(citation)

    assert repository.list_sources() == (source,)
    assert repository.list_evidence() == (evidence,)
    assert repository.list_claims() == (claim,)
    assert repository.list_citations() == (citation,)


def test_evidence_requires_existing_source() -> None:
    repository = InMemoryEvidenceRepository()
    _, evidence, _, _ = _entities()

    with pytest.raises(RepositoryIntegrityError, match="unknown source_id"):
        repository.upsert_evidence(evidence)


def test_claim_and_citation_relationships_are_checked() -> None:
    repository = InMemoryEvidenceRepository()
    source, evidence, claim, citation = _entities()
    repository.upsert_source(source)

    with pytest.raises(RepositoryIntegrityError, match="unknown evidence_ids"):
        repository.upsert_claim(claim)

    repository.upsert_evidence(evidence)
    repository.upsert_claim(claim)
    wrong_citation = citation.model_copy(
        update={"locator": EvidenceLocator(page_number=99)}
    )
    with pytest.raises(RepositoryIntegrityError, match="locator does not match"):
        repository.upsert_citation(wrong_citation)


def test_source_filtered_lists() -> None:
    repository = InMemoryEvidenceRepository()
    source, evidence, _, _ = _entities()
    other = Source.create(
        kind=SourceKind.WEB,
        title="Other",
        uri="https://example.org/other",
    )
    repository.upsert_source(source)
    repository.upsert_source(other)
    repository.upsert_evidence(evidence)

    assert repository.list_evidence(source_id=source.source_id) == (evidence,)
    assert repository.list_evidence(source_id=other.source_id) == ()


def test_pgvector_schema_and_vector_encoding_exist_without_driver() -> None:
    schema = (
        Path(__file__).parents[2]
        / "src"
        / "scholarmind"
        / "storage"
        / "schema.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema
    assert "to_tsvector('simple', text_content)" in schema
    assert PostgresEvidenceRepository._vector_literal([1, 0.25, -2]) == "[1,0.25,-2]"
    with pytest.raises(ValueError, match="must not be empty"):
        PostgresEvidenceRepository._vector_literal([])


def test_postgres_connect_defaults_to_autocommit(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    class _FakeConnection:
        autocommit = True

        def __init__(self) -> None:
            self.commit_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

    connection = _FakeConnection()

    def connect(dsn: str, *, autocommit: bool):
        calls.append((dsn, autocommit))
        return connection

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))

    repository = PostgresEvidenceRepository.connect("postgresql://example/test")
    repository._commit()

    assert calls == [("postgresql://example/test", True)]
    assert connection.commit_calls == 0
