"""Fail-closed health checks for the local ScholarMind runtime."""

from __future__ import annotations

import math
from typing import Any

from scholarmind.retrieval import OpenAIRerankProvider
from scholarmind.service import EmbeddingRuntime, VerificationMode, build_embedder
from scholarmind.storage import PostgresEvidenceRepository
from scholarmind.verification import (
    OpenAISemanticEntailmentProvider,
    VerificationStatus,
)


def check_runtime(
    *,
    dsn: str,
    runtime: EmbeddingRuntime,
    expected_dimension: int,
    verification_mode: VerificationMode = "deterministic",
    verifier_model: str = "qwen3-14b-local",
    verifier_base_url: str = "http://[::1]:8000/v1",
    verifier_api_key: str = "local-not-required",
) -> dict[str, Any]:
    """Check PostgreSQL, embeddings, and reranking without exposing secrets."""
    if not dsn.strip():
        raise ValueError("dsn must not be empty")
    if expected_dimension < 1:
        raise ValueError("expected_dimension must be positive")
    if verification_mode not in {"deterministic", "semantic"}:
        raise ValueError("unsupported verification mode")

    checks = {
        "database": _check_database(dsn, model=runtime.model),
        "embedding": _check_embedding(runtime, expected_dimension),
        "reranker": _check_reranker(runtime),
    }
    if verification_mode == "semantic":
        checks["semantic_verifier"] = _check_semantic_verifier(
            model=verifier_model,
            base_url=verifier_base_url,
            api_key=verifier_api_key,
        )
    ready = all(check["status"] == "ok" for check in checks.values())
    return {
        "status": "ready" if ready else "unavailable",
        "ready": ready,
        "checks": checks,
    }


def _check_database(dsn: str, *, model: str) -> dict[str, Any]:
    repository: PostgresEvidenceRepository | None = None
    try:
        repository = PostgresEvidenceRepository.connect(dsn)
        statistics = repository.statistics(model=model)
        if statistics["sources"] < 1 or statistics["evidence"] < 1:
            raise RuntimeError("corpus is empty")
        if statistics["indexed_embeddings"] < 1:
            raise RuntimeError("selected embedding model has no current vectors")
        return {"status": "ok", **statistics}
    except Exception as exc:
        return _failure("database_unavailable_or_unindexed", exc)
    finally:
        _close_quietly(repository)


def _check_embedding(
    runtime: EmbeddingRuntime,
    expected_dimension: int,
) -> dict[str, Any]:
    embedder = None
    try:
        embedder = build_embedder(runtime)
        vector = tuple(
            float(value)
            for value in embedder.embed_query(
                "causal dependency graph for root cause analysis"
            )
        )
        if len(vector) != expected_dimension:
            raise RuntimeError("embedding dimension mismatch")
        if not all(math.isfinite(value) for value in vector):
            raise RuntimeError("embedding contains a non-finite value")
        return {"status": "ok", "dimension": len(vector)}
    except Exception as exc:
        return _failure("embedding_service_unavailable", exc)
    finally:
        _close_quietly(embedder)


def _check_reranker(runtime: EmbeddingRuntime) -> dict[str, Any]:
    reranker = None
    try:
        reranker = OpenAIRerankProvider(
            model=runtime.model,
            base_url=runtime.base_url,
            api_key=runtime.api_key,
        )
        scores = tuple(
            float(value)
            for value in reranker.score(
                "causal root cause analysis",
                (
                    "A causal dependency graph ranks candidate root causes.",
                    "A convolutional model classifies natural images.",
                ),
            )
        )
        if len(scores) != 2 or not all(math.isfinite(value) for value in scores):
            raise RuntimeError("reranker returned invalid scores")
        if scores[0] <= scores[1]:
            raise RuntimeError("reranker failed the semantic ordering check")
        return {"status": "ok", "semantic_ordering": True}
    except Exception as exc:
        return _failure("reranker_service_unavailable", exc)
    finally:
        _close_quietly(reranker)


def _check_semantic_verifier(
    *,
    model: str,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    """Require a real structured paraphrase verdict from the configured model."""
    provider = None
    try:
        provider = OpenAISemanticEntailmentProvider(
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        verdict = provider.classify(
            "The intervention lowered mortality.",
            ("Fewer participants died after receiving the intervention.",),
        )
        if verdict.status is not VerificationStatus.SUPPORTED:
            raise RuntimeError("semantic verifier failed the entailment check")
        if verdict.supporting_indices != (1,):
            raise RuntimeError("semantic verifier returned invalid evidence links")
        return {
            "status": "ok",
            "model": model,
            "structured_output": True,
            "evidence_links_valid": True,
        }
    except Exception as exc:
        return _failure("semantic_verifier_unavailable", exc)
    finally:
        _close_quietly(provider)


def _failure(code: str, exc: Exception) -> dict[str, str]:
    """Return actionable diagnostics without echoing DSNs or endpoint payloads."""
    return {
        "status": "failed",
        "code": code,
        "error_type": type(exc).__name__,
    }


def _close_quietly(resource: Any | None) -> None:
    """Keep an optional cleanup failure from masking the health result."""
    if resource is None:
        return
    try:
        resource.close()
    except Exception:
        return
