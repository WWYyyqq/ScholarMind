"""Tests for the reusable ScholarMind research composition root."""

from __future__ import annotations

import pytest

import scholarmind.service as service_module
from scholarmind.config import ScholarMindSettings
from scholarmind.researchers import FileResearchResult, ResearchStatus
from scholarmind.service import (
    EmbeddingRuntime,
    RetrievalPipeline,
    ScholarMindResearchService,
    build_retriever,
    research_result_payload,
)


class _Repository:
    def __init__(self) -> None:
        self.closed = False

    def list_sources(self) -> tuple[object, ...]:
        return ()

    def close(self) -> None:
        self.closed = True


class _Reranker:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Embedder:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Researcher:
    def research(self, question: str) -> FileResearchResult:
        return FileResearchResult(
            question=question,
            status=ResearchStatus.FAILED,
            errors=("No evidence was retrieved.",),
        )


def test_service_releases_owned_resources_once() -> None:
    repository = _Repository()
    reranker = _Reranker()
    embedder = _Embedder()
    pipeline = RetrievalPipeline(
        retriever=object(),  # type: ignore[arg-type]
        embedder=embedder,  # type: ignore[arg-type]
        reranker=reranker,  # type: ignore[arg-type]
    )
    service = ScholarMindResearchService(
        repository,  # type: ignore[arg-type]
        _Researcher(),  # type: ignore[arg-type]
        retrieval_mode="hybrid-rerank",
        pipeline=pipeline,
    )

    with service:
        result = service.research("What changed?")

    service.close()
    assert result.status is ResearchStatus.FAILED
    assert repository.closed
    assert reranker.closed
    assert embedder.closed
    with pytest.raises(RuntimeError, match="closed"):
        service.research("Can this run again?")


def test_connect_closes_repository_when_composition_fails(monkeypatch) -> None:
    repository = _Repository()
    monkeypatch.setattr(
        "scholarmind.service.PostgresEvidenceRepository.connect",
        lambda _dsn: repository,
    )
    monkeypatch.setattr(
        "scholarmind.service.build_retriever",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad index")),
    )
    settings = ScholarMindSettings(postgres_dsn="postgresql://fixture")
    runtime = EmbeddingRuntime(
        model="fixture",
        base_url="http://localhost:8001/v1",
        api_key="local",
        query_instruction="retrieve",
    )

    with pytest.raises(RuntimeError, match="bad index"):
        ScholarMindResearchService.connect(
            settings=settings,
            runtime=runtime,
            retrieval_mode="dense",
        )

    assert repository.closed


def test_retriever_composition_closes_embedder_on_partial_failure(
    monkeypatch,
) -> None:
    embedder = _Embedder()

    class BrokenRepository:
        def list_evidence(self):
            raise RuntimeError("corpus unavailable")

    monkeypatch.setattr(service_module, "build_embedder", lambda _runtime: embedder)
    runtime = EmbeddingRuntime(
        model="fixture",
        base_url="http://localhost:8001/v1",
        api_key="local",
        query_instruction="retrieve",
    )

    with pytest.raises(RuntimeError, match="corpus unavailable"):
        build_retriever(
            BrokenRepository(),  # type: ignore[arg-type]
            runtime=runtime,
            settings=ScholarMindSettings(),
            retrieval_mode="hybrid",
        )

    assert embedder.closed


def test_research_payload_preserves_explicit_failure() -> None:
    result = FileResearchResult(
        question="What changed?",
        status=ResearchStatus.FAILED,
        errors=("No page-located evidence was found.",),
    )

    payload = research_result_payload(result, retrieval_mode="dense")

    assert payload["status"] == "failed"
    assert payload["publication_ready"] is False
    assert payload["report"] is None
    assert payload["errors"] == ["No page-located evidence was found."]
    assert payload["verifications"] == []
