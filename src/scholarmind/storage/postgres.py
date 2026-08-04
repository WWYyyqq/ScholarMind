"""Optional PostgreSQL/pgvector repository implementation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..models import Citation, Claim, Evidence, Source
from .repository import RepositoryIntegrityError

ModelT = TypeVar("ModelT", bound=BaseModel)


class OptionalPostgresDependencyError(RuntimeError):
    """Explain how to enable PostgreSQL without breaking memory-only installs."""


def _payload(value: BaseModel) -> str:
    """Encode a domain model for an explicit JSONB cast."""
    return value.model_dump_json()


def _decode(model: type[ModelT], payload: Any) -> ModelT:
    """Decode psycopg's dict payload or another driver's JSON string."""
    if isinstance(payload, str):
        return model.model_validate_json(payload)
    return model.model_validate(payload)


class PostgresEvidenceRepository:
    """DB-API-style repository; importing it never requires a PostgreSQL driver."""

    def __init__(self, connection: Any) -> None:
        """Wrap an existing DB-API compatible PostgreSQL connection."""
        self._connection = connection

    @classmethod
    def connect(cls, dsn: str, *, autocommit: bool = True) -> PostgresEvidenceRepository:
        """Open a psycopg 3 connection in repository-safe autocommit mode by default."""
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - depends on optional install
            raise OptionalPostgresDependencyError(
                "PostgreSQL storage is optional. Install `psycopg[binary]` and "
                "ensure the server has the `vector` extension, or use the memory backend."
            ) from error
        return cls(psycopg.connect(dsn, autocommit=autocommit))

    def initialize_schema(self) -> None:
        """Create idempotent tables and the pgvector extension."""
        schema_path = Path(__file__).with_name("schema.sql")
        with self._connection.cursor() as cursor:
            cursor.execute(schema_path.read_text(encoding="utf-8"))
        self._commit()

    def close(self) -> None:
        """Close the owned database connection."""
        self._connection.close()

    def _commit(self) -> None:
        """Commit when the supplied DB-API connection is transactional."""
        if bool(getattr(self._connection, "autocommit", False)):
            return
        commit = getattr(self._connection, "commit", None)
        if callable(commit):
            commit()

    def _fetch_payload(self, query: str, params: tuple[Any, ...]) -> Any | None:
        """Fetch the first payload column from one row."""
        with self._connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
        return None if row is None else row[0]

    def _list_payloads(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        """Fetch payload values in query order."""
        with self._connection.cursor() as cursor:
            cursor.execute(query, params)
            return [row[0] for row in cursor.fetchall()]

    def upsert_source(self, source: Source) -> None:
        """Insert or replace a source by stable ID."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scholarmind_sources
                    (source_id, kind, uri, content_sha256, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (source_id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    uri = EXCLUDED.uri,
                    content_sha256 = EXCLUDED.content_sha256,
                    payload = EXCLUDED.payload
                """,
                (
                    source.source_id,
                    source.kind.value,
                    source.uri,
                    source.content_sha256,
                    _payload(source),
                ),
            )
        self._commit()

    def upsert_sources(self, sources: Sequence[Source]) -> None:
        """Insert or update sources with one database batch."""
        if not sources:
            return
        rows = [
            (
                source.source_id,
                source.kind.value,
                source.uri,
                source.content_sha256,
                _payload(source),
            )
            for source in sources
        ]
        with self._connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO scholarmind_sources
                    (source_id, kind, uri, content_sha256, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (source_id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    uri = EXCLUDED.uri,
                    content_sha256 = EXCLUDED.content_sha256,
                    payload = EXCLUDED.payload
                WHERE scholarmind_sources.content_sha256
                    IS DISTINCT FROM EXCLUDED.content_sha256
                   OR scholarmind_sources.payload IS DISTINCT FROM EXCLUDED.payload
                """,
                rows,
            )
        self._commit()

    def upsert_evidence(self, evidence: Evidence) -> None:
        """Insert or replace evidence after checking source ownership."""
        if self.get_source(evidence.source_id) is None:
            raise RepositoryIntegrityError(
                f"unknown source_id {evidence.source_id!r} for evidence"
            )
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scholarmind_evidence
                    (evidence_id, source_id, text_content, content_sha256, locator, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (evidence_id) DO UPDATE SET
                    source_id = EXCLUDED.source_id,
                    text_content = EXCLUDED.text_content,
                    content_sha256 = EXCLUDED.content_sha256,
                    locator = EXCLUDED.locator,
                    payload = EXCLUDED.payload
                """,
                (
                    evidence.evidence_id,
                    evidence.source_id,
                    evidence.text,
                    evidence.content_sha256,
                    evidence.locator.model_dump_json(),
                    _payload(evidence),
                ),
            )
        self._commit()

    def upsert_evidence_batch(self, evidence: Sequence[Evidence]) -> None:
        """Validate source ownership once and upsert evidence in one batch."""
        if not evidence:
            return
        source_ids = sorted({item.source_id for item in evidence})
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_id
                FROM scholarmind_sources
                WHERE source_id = ANY(%s)
                """,
                (source_ids,),
            )
            existing_source_ids = {str(row[0]) for row in cursor.fetchall()}
            missing = sorted(set(source_ids) - existing_source_ids)
            if missing:
                raise RepositoryIntegrityError(
                    "unknown source_ids for evidence batch: " + ", ".join(missing)
                )
            cursor.executemany(
                """
                INSERT INTO scholarmind_evidence
                    (
                        evidence_id,
                        source_id,
                        text_content,
                        content_sha256,
                        locator,
                        payload
                    )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (evidence_id) DO UPDATE SET
                    source_id = EXCLUDED.source_id,
                    text_content = EXCLUDED.text_content,
                    content_sha256 = EXCLUDED.content_sha256,
                    locator = EXCLUDED.locator,
                    payload = EXCLUDED.payload
                WHERE scholarmind_evidence.content_sha256
                    IS DISTINCT FROM EXCLUDED.content_sha256
                   OR scholarmind_evidence.payload IS DISTINCT FROM EXCLUDED.payload
                """,
                [
                    (
                        item.evidence_id,
                        item.source_id,
                        item.text,
                        item.content_sha256,
                        item.locator.model_dump_json(),
                        _payload(item),
                    )
                    for item in evidence
                ],
            )
        self._commit()

    def upsert_claim(self, claim: Claim) -> None:
        """Insert or replace a claim and synchronize its evidence edges."""
        missing = [
            evidence_id
            for evidence_id in claim.evidence_ids
            if self.get_evidence(evidence_id) is None
        ]
        if missing:
            raise RepositoryIntegrityError(
                f"claim references unknown evidence_ids: {', '.join(sorted(missing))}"
            )
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scholarmind_claims
                    (claim_id, text_content, status, confidence, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (claim_id) DO UPDATE SET
                    text_content = EXCLUDED.text_content,
                    status = EXCLUDED.status,
                    confidence = EXCLUDED.confidence,
                    payload = EXCLUDED.payload
                """,
                (
                    claim.claim_id,
                    claim.text,
                    claim.status.value,
                    claim.confidence,
                    _payload(claim),
                ),
            )
            cursor.execute(
                "DELETE FROM scholarmind_claim_evidence WHERE claim_id = %s",
                (claim.claim_id,),
            )
            for evidence_id in claim.evidence_ids:
                cursor.execute(
                    """
                    INSERT INTO scholarmind_claim_evidence (claim_id, evidence_id)
                    VALUES (%s, %s)
                    """,
                    (claim.claim_id, evidence_id),
                )
        self._commit()

    def upsert_citation(self, citation: Citation) -> None:
        """Insert or replace a citation after validating the full relationship."""
        claim = self.get_claim(citation.claim_id)
        evidence = self.get_evidence(citation.evidence_id)
        source = self.get_source(citation.source_id)
        if claim is None or evidence is None or source is None:
            raise RepositoryIntegrityError(
                "citation requires an existing claim, evidence passage, and source"
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
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scholarmind_citations
                    (citation_id, claim_id, evidence_id, source_id, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (citation_id) DO UPDATE SET
                    claim_id = EXCLUDED.claim_id,
                    evidence_id = EXCLUDED.evidence_id,
                    source_id = EXCLUDED.source_id,
                    payload = EXCLUDED.payload
                """,
                (
                    citation.citation_id,
                    citation.claim_id,
                    citation.evidence_id,
                    citation.source_id,
                    _payload(citation),
                ),
            )
        self._commit()

    def get_source(self, source_id: str) -> Source | None:
        """Return a source by ID."""
        payload = self._fetch_payload(
            "SELECT payload FROM scholarmind_sources WHERE source_id = %s",
            (source_id,),
        )
        return None if payload is None else _decode(Source, payload)

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Return evidence by ID."""
        payload = self._fetch_payload(
            "SELECT payload FROM scholarmind_evidence WHERE evidence_id = %s",
            (evidence_id,),
        )
        return None if payload is None else _decode(Evidence, payload)

    def get_claim(self, claim_id: str) -> Claim | None:
        """Return a claim by ID."""
        payload = self._fetch_payload(
            "SELECT payload FROM scholarmind_claims WHERE claim_id = %s",
            (claim_id,),
        )
        return None if payload is None else _decode(Claim, payload)

    def get_citation(self, citation_id: str) -> Citation | None:
        """Return a citation by ID."""
        payload = self._fetch_payload(
            "SELECT payload FROM scholarmind_citations WHERE citation_id = %s",
            (citation_id,),
        )
        return None if payload is None else _decode(Citation, payload)

    def list_sources(self) -> tuple[Source, ...]:
        """Return all sources in stable order."""
        return tuple(
            _decode(Source, payload)
            for payload in self._list_payloads(
                "SELECT payload FROM scholarmind_sources ORDER BY source_id"
            )
        )

    def list_evidence(self, *, source_id: str | None = None) -> tuple[Evidence, ...]:
        """Return all evidence, optionally constrained to a source."""
        if source_id is None:
            payloads = self._list_payloads(
                "SELECT payload FROM scholarmind_evidence ORDER BY evidence_id"
            )
        else:
            payloads = self._list_payloads(
                """
                SELECT payload FROM scholarmind_evidence
                WHERE source_id = %s ORDER BY evidence_id
                """,
                (source_id,),
            )
        return tuple(_decode(Evidence, payload) for payload in payloads)

    def list_claims(self) -> tuple[Claim, ...]:
        """Return all claims in stable order."""
        return tuple(
            _decode(Claim, payload)
            for payload in self._list_payloads(
                "SELECT payload FROM scholarmind_claims ORDER BY claim_id"
            )
        )

    def list_citations(self, *, claim_id: str | None = None) -> tuple[Citation, ...]:
        """Return all citations, optionally constrained to a claim."""
        if claim_id is None:
            payloads = self._list_payloads(
                "SELECT payload FROM scholarmind_citations ORDER BY citation_id"
            )
        else:
            payloads = self._list_payloads(
                """
                SELECT payload FROM scholarmind_citations
                WHERE claim_id = %s ORDER BY citation_id
                """,
                (claim_id,),
            )
        return tuple(_decode(Citation, payload) for payload in payloads)

    def list_embedding_ids(self, *, model: str) -> tuple[str, ...]:
        """Return stable evidence IDs that already have this model's vector."""
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model must not be empty")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT vectors.evidence_id
                FROM scholarmind_evidence_embeddings AS vectors
                JOIN scholarmind_evidence AS evidence USING (evidence_id)
                WHERE vectors.model = %s
                  AND vectors.content_sha256 = evidence.content_sha256
                ORDER BY vectors.evidence_id
                """,
                (normalized_model,),
            )
            return tuple(str(row[0]) for row in cursor.fetchall())

    def upsert_embedding(
        self, evidence_id: str, embedding: Sequence[float], *, model: str
    ) -> None:
        """Store a model-qualified vector without importing a pgvector Python adapter."""
        evidence = self.get_evidence(evidence_id)
        if evidence is None:
            raise RepositoryIntegrityError(f"unknown evidence_id {evidence_id!r}")
        vector = self._vector_literal(embedding)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scholarmind_evidence_embeddings
                    (evidence_id, model, content_sha256, embedding)
                VALUES (%s, %s, %s, %s::vector)
                ON CONFLICT (evidence_id, model) DO UPDATE SET
                    content_sha256 = EXCLUDED.content_sha256,
                    embedding = EXCLUDED.embedding
                """,
                (evidence_id, model, evidence.content_sha256, vector),
            )
        self._commit()

    def dense_search(
        self,
        query_embedding: Sequence[float],
        *,
        model: str,
        limit: int = 8,
    ) -> tuple[tuple[Evidence, float], ...]:
        """Use pgvector cosine distance and return evidence with similarity scores."""
        if limit < 1:
            raise ValueError("limit must be positive")
        vector = self._vector_literal(query_embedding)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.payload, 1 - (v.embedding <=> %s::vector) AS score
                FROM scholarmind_evidence_embeddings AS v
                JOIN scholarmind_evidence AS e USING (evidence_id)
                WHERE v.model = %s
                  AND v.content_sha256 = e.content_sha256
                ORDER BY v.embedding <=> %s::vector, e.evidence_id
                LIMIT %s
                """,
                (vector, model, vector, limit),
            )
            rows = cursor.fetchall()
        return tuple((_decode(Evidence, row[0]), float(row[1])) for row in rows)

    @staticmethod
    def _vector_literal(values: Sequence[float]) -> str:
        """Validate and encode a non-empty finite vector for PostgreSQL casting."""
        numbers = [float(value) for value in values]
        if not numbers:
            raise ValueError("embedding must not be empty")
        if any(value != value or value in {float("inf"), float("-inf")} for value in numbers):
            raise ValueError("embedding values must be finite")
        return "[" + ",".join(format(value, ".12g") for value in numbers) + "]"
