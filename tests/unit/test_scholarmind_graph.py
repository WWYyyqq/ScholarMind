"""LangGraph contract tests without PostgreSQL, GPU, or model services."""

from __future__ import annotations

from scholarmind import graph
from scholarmind.researchers import FileResearchResult, ResearchStatus


class _Service:
    def __init__(self, result: FileResearchResult) -> None:
        self.result = result
        self.closed = False
        self.questions: list[str] = []

    def research(self, question: str) -> FileResearchResult:
        self.questions.append(question)
        return self.result

    def __enter__(self) -> _Service:
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True


def test_graph_returns_structured_pipeline_failure(monkeypatch) -> None:
    result = FileResearchResult(
        question="What changed?",
        status=ResearchStatus.FAILED,
        errors=("No page-located local evidence was retrieved.",),
    )
    service = _Service(result)
    captured: dict[str, object] = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return service

    monkeypatch.setattr(graph, "create_research_service", factory)

    output = graph.scholarmind_researcher.invoke(
        {
            "question": "  What changed?  ",
            "retrieval_mode": "dense",
            "top_k": 3,
        }
    )

    assert service.questions == ["What changed?"]
    assert service.closed
    assert captured["retrieval_mode"] == "dense"
    assert captured["top_k"] == 3
    assert output["status"] == "failed"
    assert output["publication_ready"] is False
    assert output["report"] is None
    assert output["errors"][0]["code"] == "pipeline_failed"
    assert output["counts"] == {
        "evidence": 0,
        "claims": 0,
        "published_claims": 0,
        "citations": 0,
    }


def test_graph_rejects_invalid_request_before_opening_services(monkeypatch) -> None:
    monkeypatch.setattr(
        graph,
        "create_research_service",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not open")),
    )

    output = graph.run_file_research(
        {"question": " ", "retrieval_mode": "hybrid-rerank", "top_k": 5}
    )

    assert output["status"] == "failed"
    assert output["errors"] == [
        {
            "stage": "configuration",
            "code": "invalid_request_or_configuration",
            "message": "question must be a non-empty string",
            "recoverable": False,
        }
    ]


def test_graph_converts_service_outage_to_recoverable_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        graph,
        "create_research_service",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("database offline")),
    )

    output = graph.run_file_research({"question": "What changed?"})

    assert output["status"] == "failed"
    assert output["report"] is None
    assert output["errors"][0] == {
        "stage": "research",
        "code": "research_service_unavailable",
        "message": "RuntimeError: local research service unavailable",
        "recoverable": True,
    }
