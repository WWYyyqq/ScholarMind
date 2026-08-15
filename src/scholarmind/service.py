"""Reusable composition root for ScholarMind local evidence research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from scholarmind.config import ScholarMindSettings
from scholarmind.researchers import FileResearcher, FileResearchResult
from scholarmind.retrieval import (
    EvidenceQualityPolicy,
    HybridRetriever,
    OpenAIEmbeddingProvider,
    OpenAIRerankProvider,
    PostgresDenseRetriever,
    QualityFilteredRetriever,
    RerankingRetriever,
    Retriever,
    SparseRetriever,
)
from scholarmind.storage import PostgresEvidenceRepository

RetrievalMode = Literal["dense", "hybrid", "hybrid-rerank"]
RETRIEVAL_MODES: tuple[RetrievalMode, ...] = (
    "dense",
    "hybrid",
    "hybrid-rerank",
)


@dataclass(frozen=True)
class EmbeddingRuntime:
    """Resolved OpenAI-compatible embedding endpoint configuration."""

    model: str
    base_url: str
    api_key: str
    query_instruction: str

    @classmethod
    def from_settings(cls, settings: ScholarMindSettings) -> EmbeddingRuntime:
        """Resolve an immutable runtime from project-scoped settings."""
        return cls(
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            query_instruction=settings.embedding_query_instruction,
        )


def build_embedder(runtime: EmbeddingRuntime) -> OpenAIEmbeddingProvider:
    """Build the shared OpenAI-compatible query/document embedder."""
    return OpenAIEmbeddingProvider(
        model=runtime.model,
        base_url=runtime.base_url,
        api_key=runtime.api_key,
        query_instruction=runtime.query_instruction,
    )


@dataclass
class RetrievalPipeline:
    """Retriever plus every network resource created while composing it."""

    retriever: Retriever
    embedder: OpenAIEmbeddingProvider
    reranker: OpenAIRerankProvider | None = None
    _closed: bool = False

    def close(self) -> None:
        """Release owned providers exactly once."""
        if self._closed:
            return
        self._closed = True
        if self.reranker is not None:
            self.reranker.close()
        self.embedder.close()


def build_retriever(
    repository: PostgresEvidenceRepository,
    *,
    runtime: EmbeddingRuntime,
    settings: ScholarMindSettings,
    retrieval_mode: RetrievalMode,
) -> RetrievalPipeline:
    """Build one real retrieval pipeline and return its owned reranker."""
    if retrieval_mode not in RETRIEVAL_MODES:
        raise ValueError(f"unsupported retrieval mode: {retrieval_mode}")

    embedder = build_embedder(runtime)
    reranker: OpenAIRerankProvider | None = None
    completed = False
    try:
        dense = PostgresDenseRetriever(
            repository,
            embedder=embedder,
            model=runtime.model,
        )
        if retrieval_mode == "dense":
            pipeline = RetrievalPipeline(retriever=dense, embedder=embedder)
            completed = True
            return pipeline

        quality_policy = EvidenceQualityPolicy()
        filtered_dense = QualityFilteredRetriever(
            dense,
            policy=quality_policy,
            candidate_multiplier=3,
        )
        sparse_corpus = tuple(
            item
            for item in repository.list_evidence()
            if quality_policy.assess(item).accepted
        )
        filtered_sparse = QualityFilteredRetriever(
            SparseRetriever(sparse_corpus),
            policy=quality_policy,
            candidate_multiplier=1,
        )
        hybrid: Retriever = HybridRetriever(
            filtered_dense,
            filtered_sparse,
            rrf_k=settings.rrf_k,
            dense_weight=settings.dense_weight,
            sparse_weight=settings.sparse_weight,
            candidate_multiplier=2,
        )
        if retrieval_mode == "hybrid":
            pipeline = RetrievalPipeline(retriever=hybrid, embedder=embedder)
            completed = True
            return pipeline

        reranker = OpenAIRerankProvider(
            model=runtime.model,
            base_url=runtime.base_url,
            api_key=runtime.api_key,
        )
        pipeline = RetrievalPipeline(
            retriever=RerankingRetriever(
                hybrid,
                reranker=reranker,
                candidate_multiplier=2,
            ),
            embedder=embedder,
            reranker=reranker,
        )
        completed = True
        return pipeline
    finally:
        if not completed:
            if reranker is not None:
                reranker.close()
            embedder.close()


class ScholarMindResearchService:
    """Own database/model resources for one reusable local research pipeline."""

    def __init__(
        self,
        repository: PostgresEvidenceRepository,
        researcher: FileResearcher,
        *,
        retrieval_mode: RetrievalMode,
        pipeline: RetrievalPipeline,
    ) -> None:
        """Store owned resources; callers should use this as a context manager."""
        self.repository = repository
        self.researcher = researcher
        self.retrieval_mode = retrieval_mode
        self.pipeline = pipeline
        self._closed = False

    @classmethod
    def connect(
        cls,
        *,
        settings: ScholarMindSettings | None = None,
        dsn: str | None = None,
        runtime: EmbeddingRuntime | None = None,
        retrieval_mode: RetrievalMode = "hybrid-rerank",
        top_k: int = 5,
    ) -> ScholarMindResearchService:
        """Connect PostgreSQL and compose the evidence-first research pipeline."""
        resolved_settings = settings or ScholarMindSettings.from_env()
        resolved_dsn = (dsn or resolved_settings.postgres_dsn or "").strip()
        if not resolved_dsn:
            raise ValueError(
                "SCHOLARMIND_POSTGRES_DSN is required for local evidence research"
            )
        if top_k < 1 or top_k > 100:
            raise ValueError("top_k must be between 1 and 100")

        repository = PostgresEvidenceRepository.connect(resolved_dsn)
        pipeline: RetrievalPipeline | None = None
        try:
            resolved_runtime = runtime or EmbeddingRuntime.from_settings(
                resolved_settings
            )
            pipeline = build_retriever(
                repository,
                runtime=resolved_runtime,
                settings=resolved_settings,
                retrieval_mode=retrieval_mode,
            )
            sources = {
                source.source_id: source for source in repository.list_sources()
            }
            researcher = FileResearcher(
                pipeline.retriever,
                sources=sources,
                top_k=top_k,
            )
        except Exception:
            if pipeline is not None:
                pipeline.close()
            repository.close()
            raise
        return cls(
            repository,
            researcher,
            retrieval_mode=retrieval_mode,
            pipeline=pipeline,
        )

    def research(self, question: str) -> FileResearchResult:
        """Run the configured evidence-first pipeline."""
        if self._closed:
            raise RuntimeError("research service is closed")
        return self.researcher.research(question)

    def close(self) -> None:
        """Release the reranker client and database connection exactly once."""
        if self._closed:
            return
        self._closed = True
        self.pipeline.close()
        self.repository.close()

    def __enter__(self) -> ScholarMindResearchService:
        """Return the open service."""
        if self._closed:
            raise RuntimeError("research service is closed")
        return self

    def __exit__(self, *_: object) -> None:
        """Release owned resources after a request or CLI command."""
        self.close()


def research_result_payload(
    result: FileResearchResult,
    *,
    retrieval_mode: RetrievalMode,
) -> dict[str, Any]:
    """Serialize a research result without losing verifier diagnostics."""
    return {
        "question": result.question,
        "retrieval_mode": retrieval_mode,
        "status": result.status.value,
        "publication_ready": result.publication_ready,
        "report": result.report,
        "errors": list(result.errors),
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "claims": [item.model_dump(mode="json") for item in result.claims],
        "verifications": [
            {
                **asdict(item),
                "status": item.status.value,
                "evidence_ids": list(item.evidence_ids),
            }
            for item in result.verifications
        ],
        "citations": [item.model_dump(mode="json") for item in result.citations],
    }
