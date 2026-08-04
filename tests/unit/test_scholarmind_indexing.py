"""Batch indexing tests for evidence ingestion and vector persistence."""

from collections.abc import Sequence

import pytest

from scholarmind.adapters.paper_dataset import PaperDatasetBundle
from scholarmind.models import Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.retrieval import EvidenceIndexer
from scholarmind.storage import InMemoryEvidenceRepository


class _RecordingVectorRepository(InMemoryEvidenceRepository):
    def __init__(self) -> None:
        super().__init__()
        self.embeddings: dict[tuple[str, str], tuple[float, ...]] = {}

    def upsert_embedding(
        self,
        evidence_id: str,
        embedding: Sequence[float],
        *,
        model: str,
    ) -> None:
        assert self.get_evidence(evidence_id) is not None
        self.embeddings[(evidence_id, model)] = tuple(embedding)


class _RecordingEmbedder:
    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.batches.append(tuple(texts))
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text: str) -> Sequence[float]:
        return [float(len(text)), 1.0]


def _bundle() -> PaperDatasetBundle:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Batch Indexing",
        uri="papers/indexing.pdf",
    )
    evidence = tuple(
        Evidence.create(
            source_id=source.source_id,
            text=f"Evidence passage {index}.",
            locator=EvidenceLocator(
                page_number=index,
                chunk_id=f"chunk-{index:016x}",
            ),
        )
        for index in range(1, 4)
    )
    return PaperDatasetBundle(sources=(source,), evidence=evidence)


def test_bundle_ingests_before_batch_indexing() -> None:
    bundle = _bundle()
    repository = _RecordingVectorRepository()
    embedder = _RecordingEmbedder()
    indexer = EvidenceIndexer(embedder, model="local-embedding-v1", batch_size=2)

    result = bundle.ingest_and_index(repository, indexer)

    expected_ids = tuple(sorted(item.evidence_id for item in bundle.evidence))
    assert result.model == "local-embedding-v1"
    assert result.indexed_count == 3
    assert result.evidence_ids == expected_ids
    assert result.embedding_dimension == 2
    assert [len(batch) for batch in embedder.batches] == [2, 1]
    assert repository.list_sources() == bundle.sources
    assert set(repository.embeddings) == {
        (evidence_id, "local-embedding-v1") for evidence_id in expected_ids
    }


def test_indexer_rejects_provider_count_mismatch_before_upsert() -> None:
    class _BrokenEmbedder(_RecordingEmbedder):
        def embed_documents(
            self, texts: Sequence[str]
        ) -> Sequence[Sequence[float]]:
            return []

    bundle = _bundle()
    repository = _RecordingVectorRepository()
    bundle.ingest(repository)

    with pytest.raises(ValueError, match="different number of vectors"):
        EvidenceIndexer(_BrokenEmbedder(), model="broken").index(
            bundle.evidence,
            repository,
        )

    assert repository.embeddings == {}
