"""Command-line entry point for the local ScholarMind evidence pipeline."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scholarmind.adapters.paper_dataset import (
    PaperDatasetAdapter,
    PaperDatasetBundle,
    PaperDatasetRecordError,
)
from scholarmind.config import ScholarMindSettings
from scholarmind.researchers import FileResearcher, FileResearchResult
from scholarmind.retrieval import (
    EvidenceIndexer,
    IndexingProgress,
    JsonlIndexingProgressRecorder,
    OpenAIEmbeddingProvider,
    PostgresDenseRetriever,
    SearchResult,
)
from scholarmind.storage import (
    OptionalPostgresDependencyError,
    PostgresEvidenceRepository,
)

DEFAULT_EMBEDDING_MODEL = "qwen3-embedding-0.6b-local"


class CliError(RuntimeError):
    """Represent an expected user-facing command failure."""


@dataclass(frozen=True)
class EmbeddingRuntime:
    """Resolved OpenAI-compatible embedding endpoint configuration."""

    model: str
    base_url: str
    api_key: str
    query_instruction: str


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholarmind",
        description=(
            "Index private paper chunks and run traceable local evidence research."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index_parser = commands.add_parser(
        "index",
        help="Index development-only paper chunks into PostgreSQL/pgvector.",
    )
    index_parser.add_argument(
        "--dataset",
        required=True,
        type=Path,
        help=(
            "Generated private dataset directory. Only canonical_manifest.jsonl "
            "and chunks.development.jsonl are read."
        ),
    )
    index_parser.add_argument(
        "--limit",
        type=_positive_int,
        help="Index only the first N stable evidence records for a smoke test.",
    )
    index_parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=16,
        help="Embedding request batch size (default: 16).",
    )
    index_parser.add_argument(
        "--progress-file",
        type=Path,
        help=(
            "Append JSONL progress to this path. Defaults to a private "
            ".scholarmind directory inside the dataset."
        ),
    )
    index_parser.add_argument(
        "--force-reindex",
        action="store_true",
        help="Recompute vectors even when this model is already committed.",
    )
    index_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first isolatable evidence validation failure.",
    )
    index_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count the development bundle without calling services.",
    )
    index_parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not run the idempotent database schema initializer.",
    )
    _add_runtime_arguments(index_parser)
    index_parser.set_defaults(handler=_run_index)

    search_parser = commands.add_parser(
        "search",
        help="Search indexed paper evidence with Qwen3 Embedding and pgvector.",
    )
    search_parser.add_argument("query", help="Academic search question.")
    search_parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=8,
        help="Maximum returned passages (default: 8).",
    )
    _add_runtime_arguments(search_parser)
    search_parser.set_defaults(handler=_run_search)

    research_parser = commands.add_parser(
        "research",
        help="Retrieve, verify, and cite local-paper claims.",
    )
    research_parser.add_argument("question", help="Research question.")
    research_parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=5,
        help="Maximum evidence passages supplied to the File Researcher.",
    )
    research_parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    _add_runtime_arguments(research_parser)
    research_parser.set_defaults(handler=_run_research)
    return parser


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dsn",
        help=(
            "PostgreSQL DSN. Prefer SCHOLARMIND_POSTGRES_DSN so passwords do "
            "not appear in shell history."
        ),
    )
    parser.add_argument(
        "--embedding-model",
        help=(
            "Served embedding model name (default: "
            f"{DEFAULT_EMBEDDING_MODEL})."
        ),
    )
    parser.add_argument(
        "--embedding-base-url",
        help="OpenAI-compatible embedding API base URL.",
    )


def _load_development_bundle(
    dataset_directory: Path,
    *,
    limit: int | None = None,
) -> PaperDatasetBundle:
    root = dataset_directory.expanduser().resolve()
    manifest = root / "canonical_manifest.jsonl"
    chunks = root / "chunks.development.jsonl"
    missing = [str(path) for path in (manifest, chunks) if not path.is_file()]
    if missing:
        raise CliError(
            "private dataset is incomplete; missing: " + ", ".join(missing)
        )
    bundle = PaperDatasetAdapter.load_jsonl(
        manifest,
        chunks,
        indexable_only=True,
        dataset_split="development",
    )
    if limit is None or limit >= len(bundle.evidence):
        return bundle
    evidence = bundle.evidence[:limit]
    selected_source_ids = {item.source_id for item in evidence}
    return PaperDatasetBundle(
        sources=tuple(
            source
            for source in bundle.sources
            if source.source_id in selected_source_ids
        ),
        evidence=evidence,
        dataset_split="development",
    )


def _runtime(args: argparse.Namespace) -> EmbeddingRuntime:
    settings = ScholarMindSettings.from_env()
    return EmbeddingRuntime(
        model=args.embedding_model or DEFAULT_EMBEDDING_MODEL,
        base_url=args.embedding_base_url or settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        query_instruction=settings.embedding_query_instruction,
    )


def _dsn(args: argparse.Namespace) -> str:
    settings = ScholarMindSettings.from_env()
    value = (args.dsn or settings.postgres_dsn or "").strip()
    if not value:
        raise CliError(
            "set SCHOLARMIND_POSTGRES_DSN before using PostgreSQL commands"
        )
    return value


def _index_progress_path(args: argparse.Namespace, *, model: str) -> Path:
    """Resolve a local-only progress file without leaking credentials."""
    if args.progress_file is not None:
        return args.progress_file.expanduser().resolve()
    safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", model).strip("-")
    if not safe_model:
        safe_model = "embedding"
    dataset_root = args.dataset.expanduser().resolve()
    return dataset_root / ".scholarmind" / f"index-{safe_model}.jsonl"


def _embedder(runtime: EmbeddingRuntime) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        model=runtime.model,
        base_url=runtime.base_url,
        api_key=runtime.api_key,
        query_instruction=runtime.query_instruction,
    )


def _run_index(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    bundle = _load_development_bundle(args.dataset, limit=args.limit)
    base_summary: dict[str, Any] = {
        "command": "index",
        "dataset_split": bundle.dataset_split,
        "source_count": len(bundle.sources),
        "evidence_count": len(bundle.evidence),
        "dry_run": bool(args.dry_run),
    }
    if args.dry_run:
        base_summary["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        print(json.dumps(base_summary, ensure_ascii=False, indent=2))
        return 0

    runtime = _runtime(args)
    resume = not args.force_reindex
    progress_file = _index_progress_path(args, model=runtime.model)
    recorder = JsonlIndexingProgressRecorder(
        progress_file,
        model=runtime.model,
        total_count=len(bundle.evidence),
        resume=resume,
    )

    def record_progress(progress: IndexingProgress) -> None:
        recorder(progress)
        print(
            json.dumps(
                {
                    "status": progress.status,
                    "batch_count": len(progress.evidence_ids),
                    "completed_count": progress.completed_count,
                    "total_count": progress.total_count,
                    "indexed_count": progress.indexed_count,
                    "resumed_count": progress.skipped_count,
                    "failed_count": progress.failed_count,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

    repository: PostgresEvidenceRepository | None = None
    try:
        repository = PostgresEvidenceRepository.connect(_dsn(args))
        if not args.skip_schema:
            repository.initialize_schema()
        bundle.ingest(repository)
        result = EvidenceIndexer(
            _embedder(runtime),
            model=runtime.model,
            batch_size=args.batch_size,
        ).index(
            bundle.evidence,
            repository,
            resume=resume,
            continue_on_error=not args.fail_fast,
            on_progress=record_progress,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        recorder.fail(exc, elapsed_seconds=elapsed)
        raise CliError(
            "indexing interrupted by a systemic error; fix the service and "
            f"rerun to resume from committed vectors: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if repository is not None:
            repository.close()

    elapsed = time.perf_counter() - started
    recorder.finish(result, elapsed_seconds=elapsed)
    base_summary.update(
        {
            "embedding_model": result.model,
            "embedding_dimension": result.embedding_dimension,
            "requested_count": result.total_count,
            "indexed_count": result.indexed_count,
            "resumed_count": result.skipped_count,
            "failed_count": result.failed_count,
            "complete": result.complete,
            "failures": [asdict(item) for item in result.failures],
            "progress_file": str(progress_file),
            "elapsed_seconds": round(elapsed, 3),
        }
    )
    print(json.dumps(base_summary, ensure_ascii=False, indent=2))
    return 0 if result.complete else 1


def _search_result_payload(
    result: SearchResult,
    *,
    source_titles: dict[str, str],
) -> dict[str, Any]:
    evidence = result.evidence
    return {
        "rank": result.rank,
        "score": round(result.score, 6),
        "evidence_id": evidence.evidence_id,
        "source_id": evidence.source_id,
        "source_title": source_titles.get(evidence.source_id),
        "page_number": evidence.locator.page_number,
        "section": evidence.locator.section,
        "chunk_id": evidence.locator.chunk_id,
        "text": evidence.text,
    }


def _run_search(args: argparse.Namespace) -> int:
    runtime = _runtime(args)
    repository = PostgresEvidenceRepository.connect(_dsn(args))
    try:
        retriever = PostgresDenseRetriever(
            repository,
            embedder=_embedder(runtime),
            model=runtime.model,
        )
        results = retriever.search(args.query, limit=args.top_k)
        source_titles = {
            source.source_id: source.title for source in repository.list_sources()
        }
    finally:
        repository.close()
    payload = {
        "command": "search",
        "query": " ".join(args.query.split()),
        "embedding_model": runtime.model,
        "result_count": len(results),
        "results": [
            _search_result_payload(item, source_titles=source_titles)
            for item in results
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _research_payload(result: FileResearchResult) -> dict[str, Any]:
    return {
        "command": "research",
        "question": result.question,
        "status": result.status.value,
        "publication_ready": result.publication_ready,
        "report": result.report,
        "errors": list(result.errors),
        "evidence": [
            item.model_dump(mode="json") for item in result.evidence
        ],
        "claims": [item.model_dump(mode="json") for item in result.claims],
        "citations": [
            item.model_dump(mode="json") for item in result.citations
        ],
    }


def _run_research(args: argparse.Namespace) -> int:
    runtime = _runtime(args)
    repository = PostgresEvidenceRepository.connect(_dsn(args))
    try:
        retriever = PostgresDenseRetriever(
            repository,
            embedder=_embedder(runtime),
            model=runtime.model,
        )
        sources = {
            source.source_id: source for source in repository.list_sources()
        }
        result = FileResearcher(
            retriever,
            sources=sources,
            top_k=args.top_k,
        ).research(args.question)
    finally:
        repository.close()

    if args.format == "json":
        print(json.dumps(_research_payload(result), ensure_ascii=False, indent=2))
    elif result.report:
        print(result.report)
        if result.errors:
            print("\n## Processing warnings", file=sys.stderr)
            for error in result.errors:
                print(f"- {error}", file=sys.stderr)
    else:
        print(
            json.dumps(_research_payload(result), ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
    return 0 if result.publication_ready else 2


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and execute one ScholarMind command."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        CliError,
        FileNotFoundError,
        OptionalPostgresDependencyError,
        PaperDatasetRecordError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
