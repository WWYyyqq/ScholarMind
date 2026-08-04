from types import SimpleNamespace

import pytest

from scholarmind.retrieval import OpenAIEmbeddingProvider
from scholarmind.retrieval.openai_embedding import _is_loopback_url


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        values = kwargs["input"]
        assert isinstance(values, list)
        data = [
            SimpleNamespace(index=index, embedding=[float(index), 1.0])
            for index, _ in reversed(list(enumerate(values)))
        ]
        return SimpleNamespace(data=data)


def make_provider() -> tuple[OpenAIEmbeddingProvider, FakeEmbeddings]:
    embeddings = FakeEmbeddings()
    client = SimpleNamespace(embeddings=embeddings)
    provider = OpenAIEmbeddingProvider(
        model="qwen3-embedding-local",
        base_url="http://localhost:8001/v1/",
        query_instruction="retrieve academic passages",
        client=client,
    )
    return provider, embeddings


def test_query_adds_instruction_and_returns_one_vector() -> None:
    provider, embeddings = make_provider()
    vector = provider.embed_query("  graph   neural networks  ")
    assert vector == (0.0, 1.0)
    assert embeddings.calls == [
        {
            "model": "qwen3-embedding-local",
            "input": [
                "Instruct: retrieve academic passages\n"
                "Query: graph neural networks"
            ],
            "encoding_format": "float",
        }
    ]


def test_documents_are_normalized_and_response_order_is_restored() -> None:
    provider, _ = make_provider()
    vectors = provider.embed_documents([" first  passage ", "second\npassage"])
    assert vectors == ((0.0, 1.0), (1.0, 1.0))


def test_empty_inputs_are_rejected_without_calling_endpoint() -> None:
    provider, embeddings = make_provider()
    assert provider.embed_documents([]) == ()
    with pytest.raises(ValueError, match="query text"):
        provider.embed_query("  ")
    with pytest.raises(ValueError, match="document text"):
        provider.embed_documents(["valid", "  "])
    assert embeddings.calls == []


def test_response_cardinality_must_match_request() -> None:
    client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **_: SimpleNamespace(data=[])
        )
    )
    provider = OpenAIEmbeddingProvider(
        model="qwen3-embedding-local",
        base_url="http://localhost:8001/v1",
        client=client,
    )
    with pytest.raises(RuntimeError, match="different number"):
        provider.embed_documents(["passage"])


def test_only_loopback_endpoints_bypass_environment_proxies() -> None:
    assert _is_loopback_url("http://localhost:8001/v1")
    assert _is_loopback_url("http://127.0.0.1:8001/v1")
    assert _is_loopback_url("http://[::1]:8001/v1")
    assert not _is_loopback_url("https://api.example.com/v1")
    assert not _is_loopback_url("not a URL")
