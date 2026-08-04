from __future__ import annotations

from scholarmind.models import Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.researchers import FileResearcher, ResearchStatus
from scholarmind.retrieval import SparseRetriever


def _chunk(source: Source, *, text: str, page: int, chunk_id: str) -> Evidence:
    return Evidence.create(
        source_id=source.source_id,
        text=text,
        locator=EvidenceLocator(
            page_number=page,
            section="Methods",
            chunk_id=chunk_id,
        ),
    )


def test_real_sparse_retrieval_runs_to_page_cited_local_report() -> None:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Local retrieval paper",
        uri="papers/local-retrieval.pdf",
    )
    relevant = _chunk(
        source,
        text="The BM25 retriever finds exact technical terms in local papers.",
        page=7,
        chunk_id="chunk-relevant",
    )
    distractor = _chunk(
        source,
        text="The vision appendix describes image augmentation.",
        page=2,
        chunk_id="chunk-distractor",
    )
    researcher = FileResearcher(
        SparseRetriever([distractor, relevant]),
        sources={source.source_id: source},
        top_k=1,
    )

    result = researcher.research("How does BM25 find exact technical terms?")

    assert result.status is ResearchStatus.SUCCESS
    assert result.status.value == "success"
    assert ResearchStatus.COMPLETE is ResearchStatus.SUCCESS
    assert result.publication_ready
    assert result.evidence == (relevant,)
    assert result.report is not None
    assert "The BM25 retriever finds exact technical terms" in result.report
    assert "[Local retrieval paper, p. 7]" in result.report
    assert len(result.citations) == 1
    assert result.citations[0].evidence_id == relevant.evidence_id
