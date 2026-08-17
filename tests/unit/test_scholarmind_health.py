from __future__ import annotations

from typing import Any

from scholarmind import health
from scholarmind.service import EmbeddingRuntime
from scholarmind.verification import SemanticVerdict, VerificationStatus


def _runtime() -> EmbeddingRuntime:
    return EmbeddingRuntime(
        model="fixture-embedding",
        base_url="http://127.0.0.1:8001/v1",
        api_key="local",
        query_instruction="Represent this query",
    )


class _Repository:
    closed = False

    def statistics(self, *, model: str) -> dict[str, int]:
        assert model == "fixture-embedding"
        return {"sources": 2, "evidence": 4, "indexed_embeddings": 4}

    def close(self) -> None:
        self.closed = True


class _Embedder:
    closed = False

    def embed_query(self, _text: str) -> tuple[float, ...]:
        return 0.1, 0.2, 0.3

    def close(self) -> None:
        self.closed = True


class _Reranker:
    closed = False

    def score(self, _query: str, documents: Any) -> tuple[float, ...]:
        assert len(documents) == 2
        return 0.9, 0.1

    def close(self) -> None:
        self.closed = True


class _SemanticProvider:
    closed = False

    def classify(self, _claim: str, _evidence: Any) -> SemanticVerdict:
        return SemanticVerdict(
            status=VerificationStatus.SUPPORTED,
            confidence=0.95,
            reason="The evidence entails the paraphrase.",
            supporting_indices=(1,),
        )

    def close(self) -> None:
        self.closed = True


def test_runtime_check_requires_database_embedding_and_reranker(
    monkeypatch,
) -> None:
    repository = _Repository()
    embedder = _Embedder()
    reranker = _Reranker()
    monkeypatch.setattr(
        health.PostgresEvidenceRepository,
        "connect",
        lambda _dsn: repository,
    )
    monkeypatch.setattr(health, "build_embedder", lambda _runtime: embedder)
    monkeypatch.setattr(
        health,
        "OpenAIRerankProvider",
        lambda **_kwargs: reranker,
    )

    result = health.check_runtime(
        dsn="postgresql://secret-value",
        runtime=_runtime(),
        expected_dimension=3,
    )

    assert result["status"] == "ready"
    assert result["ready"] is True
    assert result["checks"]["database"]["indexed_embeddings"] == 4
    assert result["checks"]["embedding"]["dimension"] == 3
    assert result["checks"]["reranker"]["semantic_ordering"] is True
    assert repository.closed and embedder.closed and reranker.closed


def test_runtime_check_fails_closed_without_leaking_exception_message(
    monkeypatch,
) -> None:
    secret = "do-not-print-this-password"
    monkeypatch.setattr(
        health.PostgresEvidenceRepository,
        "connect",
        lambda _dsn: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    monkeypatch.setattr(
        health,
        "build_embedder",
        lambda _runtime: (_ for _ in ()).throw(ConnectionError(secret)),
    )
    monkeypatch.setattr(
        health,
        "OpenAIRerankProvider",
        lambda **_kwargs: (_ for _ in ()).throw(ConnectionError(secret)),
    )

    result = health.check_runtime(
        dsn=f"postgresql://user:{secret}@localhost/database",
        runtime=_runtime(),
        expected_dimension=3,
    )

    assert result["status"] == "unavailable"
    assert result["ready"] is False
    assert secret not in str(result)
    assert all(
        check["status"] == "failed" for check in result["checks"].values()
    )


def test_semantic_mode_requires_real_verifier_health(monkeypatch) -> None:
    provider = _SemanticProvider()
    monkeypatch.setattr(
        health.PostgresEvidenceRepository,
        "connect",
        lambda _dsn: _Repository(),
    )
    monkeypatch.setattr(health, "build_embedder", lambda _runtime: _Embedder())
    monkeypatch.setattr(
        health,
        "OpenAIRerankProvider",
        lambda **_kwargs: _Reranker(),
    )
    monkeypatch.setattr(
        health,
        "OpenAISemanticEntailmentProvider",
        lambda **_kwargs: provider,
    )

    result = health.check_runtime(
        dsn="postgresql://fixture",
        runtime=_runtime(),
        expected_dimension=3,
        verification_mode="semantic",
        verifier_model="qwen3-test",
    )

    assert result["ready"] is True
    assert result["checks"]["semantic_verifier"]["structured_output"] is True
    assert provider.closed
