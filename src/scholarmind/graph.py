"""LangGraph API for the ScholarMind evidence-first local research agent."""

from __future__ import annotations

from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from scholarmind.config import ScholarMindSettings
from scholarmind.service import (
    RETRIEVAL_MODES,
    VERIFICATION_MODES,
    RetrievalMode,
    ScholarMindResearchService,
    VerificationMode,
    research_result_payload,
)


class AgentError(TypedDict):
    """Machine-readable error returned without turning failure into prose."""

    stage: Literal["configuration", "research"]
    code: str
    message: str
    recoverable: bool


class ScholarMindAgentState(TypedDict, total=False):
    """Serializable input and output contract exposed by LangGraph Server."""

    question: str
    retrieval_mode: RetrievalMode
    verification_mode: VerificationMode
    top_k: int
    status: Literal["success", "partial", "failed"]
    publication_ready: bool
    report: str | None
    evidence: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    verifications: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    errors: list[AgentError]
    counts: dict[str, int]


def create_research_service(
    *,
    settings: ScholarMindSettings,
    retrieval_mode: RetrievalMode,
    verification_mode: VerificationMode,
    top_k: int,
) -> ScholarMindResearchService:
    """Create the production service behind an injectable graph boundary."""
    return ScholarMindResearchService.connect(
        settings=settings,
        retrieval_mode=retrieval_mode,
        verification_mode=verification_mode,
        top_k=top_k,
    )


def run_file_research(state: ScholarMindAgentState) -> ScholarMindAgentState:
    """Run local research and always return an explicit structured status."""
    try:
        question, retrieval_mode, verification_mode, top_k = _request_from_state(
            state
        )
        settings = ScholarMindSettings.from_env()
        with create_research_service(
            settings=settings,
            retrieval_mode=retrieval_mode,
            verification_mode=verification_mode,
            top_k=top_k,
        ) as service:
            result = service.research(question)
    except (TypeError, ValueError) as exc:
        return _failure(
            state,
            stage="configuration",
            code="invalid_request_or_configuration",
            message=str(exc),
            recoverable=False,
        )
    except Exception as exc:  # API callers receive state, never fake success prose.
        return _failure(
            state,
            stage="research",
            code="research_service_unavailable",
            message=f"{type(exc).__name__}: local research service unavailable",
            recoverable=True,
        )

    payload = research_result_payload(
        result,
        retrieval_mode=retrieval_mode,
        verification_mode=verification_mode,
    )
    errors: list[AgentError] = [
        {
            "stage": "research",
            "code": (
                "pipeline_failed" if result.status.value == "failed" else "pipeline_warning"
            ),
            "message": message,
            "recoverable": result.status.value != "failed",
        }
        for message in result.errors
    ]
    return {
        **cast(ScholarMindAgentState, payload),
        "top_k": top_k,
        "errors": errors,
        "counts": {
            "evidence": len(result.evidence),
            "claims": len(result.claims),
            "published_claims": len(result.published_claims),
            "citations": len(result.citations),
        },
    }


def _request_from_state(
    state: ScholarMindAgentState,
) -> tuple[str, RetrievalMode, VerificationMode, int]:
    """Validate the small public request contract before opening resources."""
    raw_question = state.get("question")
    if not isinstance(raw_question, str) or not raw_question.strip():
        raise ValueError("question must be a non-empty string")
    question = " ".join(raw_question.split())

    raw_mode = state.get("retrieval_mode", "hybrid-rerank")
    if raw_mode not in RETRIEVAL_MODES:
        raise ValueError(
            "retrieval_mode must be dense, hybrid, or hybrid-rerank"
        )
    retrieval_mode = cast(RetrievalMode, raw_mode)

    raw_verification_mode = state.get("verification_mode", "deterministic")
    if raw_verification_mode not in VERIFICATION_MODES:
        raise ValueError(
            "verification_mode must be deterministic or semantic"
        )
    verification_mode = cast(VerificationMode, raw_verification_mode)

    raw_top_k = state.get("top_k", 5)
    if isinstance(raw_top_k, bool) or not isinstance(raw_top_k, int):
        raise TypeError("top_k must be an integer")
    if raw_top_k < 1 or raw_top_k > 100:
        raise ValueError("top_k must be between 1 and 100")
    return question, retrieval_mode, verification_mode, raw_top_k


def _failure(
    state: ScholarMindAgentState,
    *,
    stage: Literal["configuration", "research"],
    code: str,
    message: str,
    recoverable: bool,
) -> ScholarMindAgentState:
    """Build a stable failure payload with no report or unsupported claims."""
    question = state.get("question")
    raw_mode = state.get("retrieval_mode", "hybrid-rerank")
    retrieval_mode = (
        cast(RetrievalMode, raw_mode)
        if raw_mode in RETRIEVAL_MODES
        else "hybrid-rerank"
    )
    raw_verification_mode = state.get("verification_mode", "deterministic")
    verification_mode = (
        cast(VerificationMode, raw_verification_mode)
        if raw_verification_mode in VERIFICATION_MODES
        else "deterministic"
    )
    raw_top_k = state.get("top_k", 5)
    top_k = (
        raw_top_k
        if isinstance(raw_top_k, int)
        and not isinstance(raw_top_k, bool)
        and 1 <= raw_top_k <= 100
        else 5
    )
    return {
        "question": question.strip() if isinstance(question, str) else "",
        "retrieval_mode": retrieval_mode,
        "verification_mode": verification_mode,
        "top_k": top_k,
        "status": "failed",
        "publication_ready": False,
        "report": None,
        "evidence": [],
        "claims": [],
        "verifications": [],
        "citations": [],
        "errors": [
            {
                "stage": stage,
                "code": code,
                "message": message,
                "recoverable": recoverable,
            }
        ],
        "counts": {
            "evidence": 0,
            "claims": 0,
            "published_claims": 0,
            "citations": 0,
        },
    }


_builder = StateGraph(ScholarMindAgentState)
_builder.add_node("file_research", run_file_research)
_builder.add_edge(START, "file_research")
_builder.add_edge("file_research", END)

scholarmind_researcher = _builder.compile()
