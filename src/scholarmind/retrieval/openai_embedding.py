"""OpenAI-compatible embedding provider for the local vLLM service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse


class OpenAIEmbeddingProvider:
    """Embed queries and documents through an OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str = "local-not-required",
        query_instruction: str | None = None,
        client: Any | None = None,
    ) -> None:
        """Configure a local or remote embeddings endpoint."""
        if not model.strip():
            raise ValueError("model must not be empty")
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.query_instruction = (
            " ".join(query_instruction.split()) if query_instruction else None
        )
        self._client = client or self._build_client(api_key)

    def _build_client(self, api_key: str) -> Any:
        """Import the SDK lazily so deterministic retrieval stays lightweight."""
        try:
            from openai import DefaultHttpxClient, OpenAI
        except ImportError as error:  # pragma: no cover - base app installs openai
            raise RuntimeError(
                "The OpenAI SDK is required for the vLLM embedding provider."
            ) from error
        options: dict[str, Any] = {
            "base_url": self.base_url,
            "api_key": api_key,
            "timeout": 180.0,
            "max_retries": 2,
        }
        if _is_loopback_url(self.base_url):
            options["http_client"] = DefaultHttpxClient(trust_env=False)
        return OpenAI(**options)

    def embed_query(self, text: str) -> Sequence[float]:
        """Embed one query with the configured retrieval instruction."""
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("query text must not be empty")
        if self.query_instruction:
            normalized = (
                f"Instruct: {self.query_instruction}\nQuery: {normalized}"
            )
        return self._embed((normalized,))[0]

    def embed_documents(
        self, texts: Sequence[str]
    ) -> Sequence[Sequence[float]]:
        """Embed a non-empty batch of document passages without query prompts."""
        normalized = tuple(" ".join(text.split()) for text in texts)
        if not normalized:
            return ()
        if any(not text for text in normalized):
            raise ValueError("document text must not be empty")
        return self._embed(normalized)

    def _embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Call the endpoint and restore the response's input order."""
        response = self._client.embeddings.create(
            model=self.model,
            input=list(texts),
            encoding_format="float",
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise RuntimeError(
                "embedding endpoint returned a different number of vectors"
            )
        vectors = tuple(
            tuple(float(value) for value in item.embedding)
            for item in ordered
        )
        if any(not vector for vector in vectors):
            raise RuntimeError("embedding endpoint returned an empty vector")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise RuntimeError(
                "embedding endpoint returned inconsistent vector dimensions"
            )
        return vectors


def _is_loopback_url(value: str) -> bool:
    """Return whether an API URL must bypass inherited system proxies."""
    try:
        return urlparse(value).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False
