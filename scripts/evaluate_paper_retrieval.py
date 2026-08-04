#!/usr/bin/env python3
"""Compare dense, hybrid, and reranked retrieval on private Silver labels."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

from scholarmind.config import ScholarMindSettings
from scholarmind.retrieval import (
    EvidenceQualityPolicy,
    HybridRetriever,
    OpenAIEmbeddingProvider,
    OpenAIRerankProvider,
    PostgresDenseRetriever,
    QualityFilteredRetriever,
    RerankingRetriever,
    Retriever,
    SearchResult,
    SparseRetriever,
)
from scholarmind.storage import PostgresEvidenceRepository

RetrievalMode = Literal["dense", "hybrid", "hybrid-rerank"]
DEFAULT_MODEL = "qwen3-embedding-0.6b-local"


@dataclass(frozen=True, slots=True)
class SilverQuestion:
    """Private question and locator used only during one local evaluation run."""

    question_id: str
    question: str
    paper_id: str
    page_number: int
    evidence_text: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Content-free ranking diagnostics safe to inspect in aggregate."""

    question_id: str
    source_rank: int | None
    page_rank: int | None
    exact_rank: int | None
    retrieved_count: int
    rejected_result_count: int
    elapsed_seconds: float


def _positive_int(value: str) -> int:
    """Parse a positive CLI integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    """Build the private-label retrieval evaluation CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate local retrieval without writing question, answer, or evidence "
            "text to the result artifact."
        )
    )
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--top-k", type=_positive_int, default=8)
    parser.add_argument("--limit", type=_positive_int)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("dense", "hybrid", "hybrid-rerank"),
        default=("dense", "hybrid", "hybrid-rerank"),
    )
    parser.add_argument("--dsn")
    parser.add_argument("--embedding-model", default=DEFAULT_MODEL)
    parser.add_argument("--embedding-base-url")
    return parser


def _required_string(
    record: dict[str, Any],
    key: str,
    *,
    location: str,
) -> str:
    """Read one required non-empty string from a Silver row."""
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: {key} must be a non-empty string")
    return value.strip()


def load_silver_questions(path: Path) -> tuple[SilverQuestion, ...]:
    """Load only fields required for source, page, and exact-text ranking."""
    questions: list[SilverQuestion] = []
    seen_ids: set[str] = set()
    with path.expanduser().resolve().open(encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            location = f"{path}:{line_number}"
            record = json.loads(raw_line)
            if not isinstance(record, dict):
                raise ValueError(f"{location}: row must be an object")
            question_id = _required_string(
                record,
                "question_id",
                location=location,
            )
            if question_id in seen_ids:
                raise ValueError(f"{location}: duplicate question_id {question_id}")
            evidence = record.get("evidence")
            if not isinstance(evidence, dict):
                raise ValueError(f"{location}: evidence must be an object")
            page_number = evidence.get("page_number")
            if not isinstance(page_number, int) or page_number < 1:
                raise ValueError(f"{location}: evidence.page_number must be positive")
            evidence_text = evidence.get("text")
            if not isinstance(evidence_text, str) or not evidence_text.strip():
                raise ValueError(
                    f"{location}: evidence.text must be a non-empty string"
                )
            questions.append(
                SilverQuestion(
                    question_id=question_id,
                    question=_required_string(
                        record,
                        "question",
                        location=location,
                    ),
                    paper_id=_required_string(
                        record,
                        "paper_id",
                        location=location,
                    ),
                    page_number=page_number,
                    evidence_text=evidence_text.strip(),
                )
            )
            seen_ids.add(question_id)
    if not questions:
        raise ValueError(f"{path}: no Silver questions found")
    return tuple(questions)


def _normal_text(value: str) -> str:
    """Normalize whitespace and case for local label matching."""
    return " ".join(value.casefold().split())


def _first_rank(
    results: list[SearchResult],
    predicate: Any,
) -> int | None:
    """Return the first one-based rank satisfying a relevance predicate."""
    for result in results:
        if predicate(result):
            return result.rank
    return None


def _build_retriever(
    mode: RetrievalMode,
    *,
    repository: PostgresEvidenceRepository,
    settings: ScholarMindSettings,
    model: str,
    base_url: str,
    accepted_corpus: tuple[Any, ...],
    quality_policy: EvidenceQualityPolicy,
) -> tuple[Retriever, OpenAIRerankProvider | None]:
    """Build one reusable real retrieval strategy for all benchmark cases."""
    embedder = OpenAIEmbeddingProvider(
        model=model,
        base_url=base_url,
        api_key=settings.embedding_api_key,
        query_instruction=settings.embedding_query_instruction,
    )
    dense = PostgresDenseRetriever(
        repository,
        embedder=embedder,
        model=model,
    )
    if mode == "dense":
        return dense, None

    filtered_dense = QualityFilteredRetriever(
        dense,
        policy=quality_policy,
        candidate_multiplier=3,
    )
    filtered_sparse = QualityFilteredRetriever(
        SparseRetriever(accepted_corpus),
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
    if mode == "hybrid":
        return hybrid, None

    reranker = OpenAIRerankProvider(
        model=model,
        base_url=base_url,
        api_key=settings.embedding_api_key,
    )
    return (
        RerankingRetriever(
            hybrid,
            reranker=reranker,
            candidate_multiplier=2,
        ),
        reranker,
    )


def _evaluate_case(
    question: SilverQuestion,
    *,
    relevant_source_id: str,
    retriever: Retriever,
    policy: EvidenceQualityPolicy,
    top_k: int,
) -> CaseResult:
    """Evaluate source, page, and exact-text hits without returning content."""
    started = time.perf_counter()
    results = retriever.search(question.question, limit=top_k)
    elapsed = time.perf_counter() - started
    normalized_label = _normal_text(question.evidence_text)

    def same_source(result: SearchResult) -> bool:
        return result.evidence.source_id == relevant_source_id

    def same_page(result: SearchResult) -> bool:
        return (
            same_source(result)
            and result.evidence.locator.page_number == question.page_number
        )

    def exact_text(result: SearchResult) -> bool:
        if not same_page(result):
            return False
        retrieved = _normal_text(result.evidence.text)
        return normalized_label in retrieved or retrieved in normalized_label

    return CaseResult(
        question_id=question.question_id,
        source_rank=_first_rank(results, same_source),
        page_rank=_first_rank(results, same_page),
        exact_rank=_first_rank(results, exact_text),
        retrieved_count=len(results),
        rejected_result_count=sum(
            not policy.assess(result.evidence).accepted for result in results
        ),
        elapsed_seconds=round(elapsed, 3),
    )


def _mean_reciprocal_rank(ranks: list[int | None]) -> float:
    """Compute MRR for a list with at most one relevant target per case."""
    return fmean(0.0 if rank is None else 1.0 / rank for rank in ranks)


def _summarize(cases: list[CaseResult]) -> dict[str, float | int]:
    """Aggregate content-free ranking and noise metrics."""
    if not cases:
        raise ValueError("at least one case is required")
    retrieved = sum(case.retrieved_count for case in cases)
    rejected = sum(case.rejected_result_count for case in cases)

    def recall(field: str) -> float:
        return fmean(getattr(case, field) is not None for case in cases)

    return {
        "case_count": len(cases),
        "source_recall_at_k": round(recall("source_rank"), 6),
        "page_recall_at_k": round(recall("page_rank"), 6),
        "exact_recall_at_k": round(recall("exact_rank"), 6),
        "source_mrr": round(
            _mean_reciprocal_rank([case.source_rank for case in cases]),
            6,
        ),
        "page_mrr": round(
            _mean_reciprocal_rank([case.page_rank for case in cases]),
            6,
        ),
        "exact_mrr": round(
            _mean_reciprocal_rank([case.exact_rank for case in cases]),
            6,
        ),
        "rejected_result_rate": round(
            rejected / retrieved if retrieved else 0.0,
            6,
        ),
        "mean_latency_seconds": round(
            fmean(case.elapsed_seconds for case in cases),
            3,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Run selected retrieval modes and write a private content-free artifact."""
    args = _parser().parse_args(argv)
    settings = ScholarMindSettings.from_env()
    dsn = (args.dsn or settings.postgres_dsn or "").strip()
    if not dsn:
        raise ValueError("set SCHOLARMIND_POSTGRES_DSN or pass --dsn")
    model = args.embedding_model.strip()
    base_url = args.embedding_base_url or settings.embedding_base_url
    questions = load_silver_questions(args.questions)
    if args.limit is not None:
        questions = questions[: args.limit]

    repository = PostgresEvidenceRepository.connect(dsn)
    try:
        sources_by_paper = {
            source.paper_id: source.source_id
            for source in repository.list_sources()
            if source.paper_id
        }
        missing_papers = sorted(
            {question.paper_id for question in questions} - sources_by_paper.keys()
        )
        if missing_papers:
            raise ValueError(
                f"{len(missing_papers)} labeled papers are absent from PostgreSQL"
            )

        quality_policy = EvidenceQualityPolicy()
        all_evidence = repository.list_evidence()
        accepted_corpus = tuple(
            item for item in all_evidence if quality_policy.assess(item).accepted
        )
        mode_results: dict[str, Any] = {}
        for raw_mode in args.modes:
            mode: RetrievalMode = raw_mode
            retriever, reranker = _build_retriever(
                mode,
                repository=repository,
                settings=settings,
                model=model,
                base_url=base_url,
                accepted_corpus=accepted_corpus,
                quality_policy=quality_policy,
            )
            try:
                cases = [
                    _evaluate_case(
                        question,
                        relevant_source_id=sources_by_paper[question.paper_id],
                        retriever=retriever,
                        policy=quality_policy,
                        top_k=args.top_k,
                    )
                    for question in questions
                ]
            finally:
                if reranker is not None:
                    reranker.close()
            mode_results[mode] = {
                "summary": _summarize(cases),
                "cases": [asdict(case) for case in cases],
            }
    finally:
        repository.close()

    artifact = {
        "schema_version": "1.0.0",
        "created_at": datetime.now(UTC).isoformat(),
        "label_status": "silver_not_human_verified",
        "content_policy": (
            "question, answer, evidence text, paper title, and credentials omitted"
        ),
        "model": model,
        "top_k": args.top_k,
        "question_count": len(questions),
        "corpus_evidence_count": len(all_evidence),
        "accepted_corpus_count": len(accepted_corpus),
        "quality_rejected_corpus_count": len(all_evidence) - len(accepted_corpus),
        "modes": mode_results,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "label_status": artifact["label_status"],
                "question_count": len(questions),
                "top_k": args.top_k,
                "accepted_corpus_count": len(accepted_corpus),
                "quality_rejected_corpus_count": (
                    len(all_evidence) - len(accepted_corpus)
                ),
                "summaries": {
                    mode: result["summary"]
                    for mode, result in mode_results.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
