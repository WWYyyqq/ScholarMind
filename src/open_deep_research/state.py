"""Graph state definitions and data structures for the Deep Research agent."""

import operator
from typing import Annotated, Literal, Optional

from langchain_core.messages import MessageLikeRepresentation
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict


###################
# Structured Outputs
###################
class ConductResearch(BaseModel):
    """Call this tool to conduct research on a specific topic."""
    research_topic: str = Field(
        description="The topic to research. Should be a single topic, and should be described in high detail (at least a paragraph).",
    )

class ResearchComplete(BaseModel):
    """Call this tool to indicate that the research is complete."""

class Summary(BaseModel):
    """Research summary with key findings."""
    
    summary: str
    key_excerpts: str

class ClarifyWithUser(BaseModel):
    """Model for user clarification requests."""
    
    need_clarification: bool = Field(
        description="Whether the user needs to be asked a clarifying question.",
    )
    question: str = Field(
        description="A question to ask the user to clarify the report scope",
    )
    verification: str = Field(
        description="Verify message that we will start research after the user has provided the necessary information.",
    )

class ResearchQuestion(BaseModel):
    """Research question and brief for guiding research."""
    
    research_brief: str = Field(
        description="A research question that will be used to guide the research.",
    )


###################
# State Definitions
###################

ResearchStatus = Literal["success", "partial", "failed"]


class ResearchEvidence(TypedDict):
    """Provenance record for one successful research tool observation."""

    evidence_id: str
    source: Literal["tool", "native_search"]
    tool_name: str
    tool_call_id: str
    content_hash: str
    content: str


class ResearchError(TypedDict):
    """Machine-readable reason for a degraded or failed research run."""

    stage: Literal["supervisor", "researcher", "tool", "compression", "writer"]
    code: str
    message: str
    recoverable: bool
    research_topic: NotRequired[str]
    tool_name: NotRequired[str]
    tool_call_id: NotRequired[str]


def override_reducer(current_value, new_value):
    """Reducer function that allows overriding values in state."""
    if isinstance(new_value, dict) and new_value.get("type") == "override":
        return new_value.get("value", new_value)
    else:
        return operator.add(current_value, new_value)
    
class AgentInputState(MessagesState):
    """InputState is only 'messages'."""

class AgentState(MessagesState):
    """Main agent state containing messages and research data."""
    
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    research_brief: Optional[str]
    raw_notes: Annotated[list[str], override_reducer] = []
    notes: Annotated[list[str], override_reducer] = []
    final_report: str
    research_status: ResearchStatus
    research_errors: Annotated[list[ResearchError], operator.add] = []
    evidence_count: Annotated[int, operator.add] = 0
    evidence_records: Annotated[list[ResearchEvidence], operator.add] = []

class SupervisorState(TypedDict):
    """State for the supervisor that manages research tasks."""
    
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    research_brief: str
    notes: Annotated[list[str], override_reducer] = []
    research_iterations: int = 0
    raw_notes: Annotated[list[str], override_reducer] = []
    research_status: ResearchStatus
    research_errors: Annotated[list[ResearchError], operator.add] = []
    evidence_count: Annotated[int, operator.add] = 0
    evidence_records: Annotated[list[ResearchEvidence], operator.add] = []
    successful_research_units: Annotated[int, operator.add] = 0
    failed_research_units: Annotated[int, operator.add] = 0

class ResearcherState(TypedDict):
    """State for individual researchers conducting research."""
    
    researcher_messages: Annotated[list[MessageLikeRepresentation], operator.add]
    tool_call_iterations: int = 0
    research_topic: str
    compressed_research: str
    raw_notes: Annotated[list[str], override_reducer] = []
    research_status: ResearchStatus
    research_errors: Annotated[list[ResearchError], operator.add] = []
    evidence_count: Annotated[int, operator.add] = 0
    evidence_records: Annotated[list[ResearchEvidence], operator.add] = []

class ResearcherOutputState(BaseModel):
    """Output state from individual researchers."""
    
    compressed_research: str
    raw_notes: Annotated[list[str], override_reducer] = []
    research_status: ResearchStatus = "failed"
    research_errors: list[ResearchError] = Field(default_factory=list)
    evidence_count: int = 0
    evidence_records: list[ResearchEvidence] = Field(default_factory=list)
