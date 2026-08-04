"""Second-stage reranking through a local OpenAI-compatible HTTP service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .types import Retriever, SearchResult


class RerankProvider(Protocol):
    """Score query-document pairs for second-stage retrieval."""

    def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Return one relevance score per input document."""
        ...


class OpenAIRerankProvider:
    """Call the vLLM-compatible rerank endpoint without inheriting local proxies."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str = "local-not-required",
        timeout: float = 180.0,
        client: Any | None = None,
    ) -> None:
        """Configure a rerank endpoint and optional test client."""
        normalized_model = model.strip()
        normalized_url = base_url.rstrip("/")
        if not normalized_model:
            raise ValueError("model must not be empty")
        if not normalized_url:
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.model = normalized_model
        rerank_base_url = normalized_url.removesuffix("/v1")
        self.endpoint = rerank_base_url + "/rerank"
        self._owns_client = client is None
        if client is None:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            client = httpx.Client(
                headers=headers,
                timeout=timeout,
                trust_env=not _is_loopback_url(normalized_url),
            )
        self._client = client

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        """Score normalized documents and restore their input order."""
        normalized_query = " ".join(query.split())
        normalized_documents = tuple(" ".join(text.split()) for text in documents)
        if not normalized_query:
            raise ValueError("query text must not be empty")
        if not normalized_documents:
            return ()
        if any(not text for text in normalized_documents):
            raise ValueError("document text must not be empty")

        response = self._client.post(
            self.endpoint,
            json={
                "model": self.model,
                "query": normalized_query,
                "documents": list(normalized_documents),
                "top_n": len(normalized_documents),
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError("rerank endpoint returned no results list")

        scores: list[float | None] = [None] * len(normalized_documents)
        for item in raw_results:
            if not isinstance(item, dict):
                raise RuntimeError("rerank endpoint returned an invalid result")
            index = item.get("index")
            relevance_score = item.get("relevance_score")
            if (
                not isinstance(index, int)
                or isinstance(relevance_score, bool)
                or not isinstance(relevance_score, int | float)
                or index < 0
                or index >= len(scores)
                or scores[index] is not None
            ):
                raise RuntimeError("rerank endpoint returned invalid result indices")
            scores[index] = float(relevance_score)
        if any(score is None for score in scores):
            raise RuntimeError(
                "rerank endpoint returned a different number of scores"
            )
        return tuple(float(score) for score in scores if score is not None)

    def close(self) -> None:
        """Close an internally owned HTTP client."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAIRerankProvider:
        """Return the provider for context-managed callers."""
        return self

    def __exit__(self, *_: object) -> None:
        """Release the HTTP client."""
        self.close()


class RerankingRetriever:
    """Over-fetch candidates and order them using a relevance provider."""

    def __init__(
        self,
        retriever: Retriever,
        *,
        reranker: RerankProvider,
        candidate_multiplier: int = 3,
    ) -> None:
        """Configure the candidate retriever and reranking budget."""
        if candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be positive")
        self.retriever = retriever
        self.reranker = reranker
        self.candidate_multiplier = candidate_multiplier

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Return candidates ordered by second-stage relevance."""
        if limit < 1:
            raise ValueError("limit must be positive")
        normalized_query = " ".join(query.split())
        if not normalized_query:
            return []
        candidates = self.retriever.search(
            normalized_query,
            limit=limit * self.candidate_multiplier,
        )
        if not candidates:
            return []
        scores = tuple(
            float(value)
            for value in self.reranker.score(
                normalized_query,
                [candidate.evidence.text for candidate in candidates],
            )
        )
        if len(scores) != len(candidates):
            raise RuntimeError("reranker returned a different number of scores")
        ordered = sorted(
            zip(candidates, scores),
            key=lambda pair: (
                -pair[1],
                pair[0].rank,
                pair[0].evidence.evidence_id,
            ),
        )
        return [
            candidate.model_copy(
                update={
                    "score": reranker_score,
                    "rank": rank,
                    "reranker_score": reranker_score,
                }
            )
            for rank, (candidate, reranker_score) in enumerate(
                ordered[:limit],
                start=1,
            )
        ]


def _is_loopback_url(value: str) -> bool:
    """Return whether an API URL should bypass environment proxies."""
    try:
        return urlparse(value).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False
