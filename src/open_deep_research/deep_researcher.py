"""Main LangGraph implementation for the Deep Research agent."""

import asyncio
import hashlib
import json
from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    get_buffer_string,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from open_deep_research.configuration import (
    Configuration,
)
from open_deep_research.prompts import (
    clarify_with_user_instructions,
    compress_research_simple_human_message,
    compress_research_system_prompt,
    final_report_generation_prompt,
    lead_researcher_prompt,
    research_system_prompt,
    transform_messages_into_research_topic_prompt,
)
from open_deep_research.state import (
    AgentInputState,
    AgentState,
    ClarifyWithUser,
    ConductResearch,
    ResearchComplete,
    ResearcherOutputState,
    ResearchError,
    ResearcherState,
    ResearchEvidence,
    ResearchQuestion,
    ResearchStatus,
    SupervisorState,
)
from open_deep_research.utils import (
    anthropic_websearch_called,
    get_all_tools,
    get_api_key_for_model,
    get_base_url_for_model,
    get_model_token_limit,
    get_notes_from_tool_calls,
    get_today_str,
    is_token_limit_exceeded,
    openai_websearch_called,
    remove_up_to_last_ai_message,
    think_tool,
)

# Initialize a configurable model that we will use throughout the agent
configurable_model = init_chat_model(
    configurable_fields=("model", "max_tokens", "api_key", "base_url"),
)

def _research_error(
    stage: Literal["supervisor", "researcher", "tool", "compression", "writer"],
    code: str,
    message: str,
    *,
    recoverable: bool,
    research_topic: str | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
) -> ResearchError:
    """Build a JSON-serializable error detail shared across graph layers."""
    error: ResearchError = {
        "stage": stage,
        "code": code,
        "message": message,
        "recoverable": recoverable,
    }
    if research_topic:
        error["research_topic"] = research_topic
    if tool_name:
        error["tool_name"] = tool_name
    if tool_call_id:
        error["tool_call_id"] = tool_call_id
    return error


def _tool_error_content(error: ResearchError) -> str:
    """Serialize a Tool Error without relying on exception-only event channels."""
    return json.dumps(
        {"type": "tool_error", "error": error},
        ensure_ascii=False,
        sort_keys=True,
    )


def _parse_tool_error(value: Any) -> ResearchError | None:
    """Return a structured Tool Error embedded in a tool observation, if present."""
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "tool_error":
        return None
    error = payload.get("error")
    return error if isinstance(error, dict) else None


def _content_text(value: Any) -> str:
    """Normalize common model and tool result values for notes and validation."""
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).strip()
    except (TypeError, ValueError):
        return str(value).strip()


def _is_valid_evidence_content(value: Any) -> bool:
    """Reject blank observations and known error placeholders as evidence."""
    content = _content_text(value)
    if not content or _parse_tool_error(content):
        return False
    lowered = content.lower()
    return not lowered.startswith(
        (
            "error executing tool:",
            "error synthesizing research report:",
            "tool error:",
        )
    )


def _content_hash(content: str) -> str:
    """Return the canonical SHA-256 digest for evidence content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _evidence_id(
    source: Literal["tool", "native_search"],
    tool_name: str,
    tool_call_id: str,
    content_hash: str,
) -> str:
    """Derive a stable evidence ID from provenance and content identity."""
    identity = "\0".join(
        (source, tool_name, tool_call_id, content_hash)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _make_evidence_record(
    *,
    source: Literal["tool", "native_search"],
    tool_name: str,
    tool_call_id: str,
    value: Any,
) -> ResearchEvidence | None:
    """Create a provenance record only for a successful non-error output."""
    content = _content_text(value)
    if not _is_valid_evidence_content(content):
        return None
    content_hash = _content_hash(content)
    return {
        "evidence_id": _evidence_id(
            source,
            tool_name,
            tool_call_id,
            content_hash,
        ),
        "source": source,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "content_hash": content_hash,
        "content": content,
    }


def _valid_evidence_records(records: list[Any]) -> list[ResearchEvidence]:
    """Validate evidence provenance, hashes, stable IDs, and uniqueness."""
    valid: list[ResearchEvidence] = []
    seen_ids: set[str] = set()
    for candidate in records:
        if not isinstance(candidate, dict):
            continue
        source = candidate.get("source")
        tool_name = candidate.get("tool_name")
        tool_call_id = candidate.get("tool_call_id")
        content_hash = candidate.get("content_hash")
        content = candidate.get("content")
        evidence_id = candidate.get("evidence_id")
        if (
            source not in {"tool", "native_search"}
            or not isinstance(tool_name, str)
            or not tool_name
            or not isinstance(tool_call_id, str)
            or not tool_call_id
            or not isinstance(content_hash, str)
            or not isinstance(content, str)
            or not isinstance(evidence_id, str)
            or not _is_valid_evidence_content(content)
        ):
            continue
        expected_hash = _content_hash(content)
        expected_id = _evidence_id(
            source,
            tool_name,
            tool_call_id,
            expected_hash,
        )
        if content_hash != expected_hash or evidence_id != expected_id:
            continue
        if evidence_id in seen_ids:
            continue
        seen_ids.add(evidence_id)
        valid.append(
            {
                "evidence_id": evidence_id,
                "source": source,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "content_hash": content_hash,
                "content": content,
            }
        )
    return valid


def _evidence_findings(records: list[ResearchEvidence]) -> str:
    """Render validated evidence records for the report prompt."""
    return "\n\n".join(
        (
            f"[Evidence {record['evidence_id']}] "
            f"tool={record['tool_name']} "
            f"call={record['tool_call_id']}\n"
            f"{record['content']}"
        )
        for record in records
    )

def _valid_research_notes(notes: list[Any]) -> list[str]:
    """Return only non-error research notes suitable for the Writer."""
    return [
        content
        for note in notes
        if _is_valid_evidence_content(note)
        and (content := _content_text(note))
    ]


def _raw_evidence_from_messages(messages: list[Any]) -> str:
    """Collect only successful tool or native-search outputs as fallback evidence."""
    evidence: list[str] = []
    for message in messages:
        if (
            isinstance(message, ToolMessage)
            and message.name not in {"think_tool", "ResearchComplete"}
        ):
            if _is_valid_evidence_content(message.content):
                evidence.append(_content_text(message.content))
        elif isinstance(message, AIMessage) and (
            openai_websearch_called(message) or anthropic_websearch_called(message)
        ):
            if _is_valid_evidence_content(message.content):
                evidence.append(_content_text(message.content))
    return "\n".join(evidence)

async def clarify_with_user(state: AgentState, config: RunnableConfig) -> Command[Literal["write_research_brief", "__end__"]]:
    """Analyze user messages and ask clarifying questions if the research scope is unclear.
    
    This function determines whether the user's request needs clarification before proceeding
    with research. If clarification is disabled or not needed, it proceeds directly to research.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings and preferences
        
    Returns:
        Command to either end with a clarifying question or proceed to research brief
    """
    # Step 1: Check if clarification is enabled in configuration
    configurable = Configuration.from_runnable_config(config)
    if not configurable.allow_clarification:
        # Skip clarification step and proceed directly to research
        return Command(goto="write_research_brief")
    
    # Step 2: Prepare the model for structured clarification analysis
    messages = state["messages"]
    model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "base_url": get_base_url_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Configure model with structured output and retry logic
    clarification_model = (
        configurable_model
        .with_structured_output(ClarifyWithUser)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(model_config)
    )
    
    # Step 3: Analyze whether clarification is needed
    prompt_content = clarify_with_user_instructions.format(
        messages=get_buffer_string(messages), 
        date=get_today_str()
    )
    response = await clarification_model.ainvoke([HumanMessage(content=prompt_content)])
    
    # Step 4: Route based on clarification analysis
    if response.need_clarification:
        # End with clarifying question for user
        return Command(
            goto=END, 
            update={"messages": [AIMessage(content=response.question)]}
        )
    else:
        # Proceed to research with verification message
        return Command(
            goto="write_research_brief", 
            update={"messages": [AIMessage(content=response.verification)]}
        )


async def write_research_brief(state: AgentState, config: RunnableConfig) -> Command[Literal["research_supervisor"]]:
    """Transform user messages into a structured research brief and initialize supervisor.
    
    This function analyzes the user's messages and generates a focused research brief
    that will guide the research supervisor. It also sets up the initial supervisor
    context with appropriate prompts and instructions.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to research supervisor with initialized context
    """
    # Step 1: Set up the research model for structured output
    configurable = Configuration.from_runnable_config(config)
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "base_url": get_base_url_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Configure model for structured research question generation
    research_model = (
        configurable_model
        .with_structured_output(ResearchQuestion)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    # Step 2: Generate structured research brief from user messages
    prompt_content = transform_messages_into_research_topic_prompt.format(
        messages=get_buffer_string(state.get("messages", [])),
        date=get_today_str()
    )
    response = await research_model.ainvoke([HumanMessage(content=prompt_content)])
    
    # Step 3: Initialize supervisor with research brief and instructions
    supervisor_system_prompt = lead_researcher_prompt.format(
        date=get_today_str(),
        max_concurrent_research_units=configurable.max_concurrent_research_units,
        max_researcher_iterations=configurable.max_researcher_iterations
    )
    
    return Command(
        goto="research_supervisor", 
        update={
            "research_brief": response.research_brief,
            "supervisor_messages": {
                "type": "override",
                "value": [
                    SystemMessage(content=supervisor_system_prompt),
                    HumanMessage(content=response.research_brief)
                ]
            }
        }
    )


async def supervisor(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor_tools"]]:
    """Lead research supervisor that plans research strategy and delegates to researchers.
    
    The supervisor analyzes the research brief and decides how to break down the research
    into manageable tasks. It can use think_tool for strategic planning, ConductResearch
    to delegate tasks to sub-researchers, or ResearchComplete when satisfied with findings.
    
    Args:
        state: Current supervisor state with messages and research context
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to supervisor_tools for tool execution
    """
    # Step 1: Configure the supervisor model with available tools
    configurable = Configuration.from_runnable_config(config)
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "base_url": get_base_url_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Available tools: research delegation, completion signaling, and strategic thinking
    lead_researcher_tools = [ConductResearch, ResearchComplete, think_tool]
    
    # Configure model with tools, retry logic, and model settings
    research_model = (
        configurable_model
        .bind_tools(lead_researcher_tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    # Step 2: Generate supervisor response based on current context
    supervisor_messages = state.get("supervisor_messages", [])
    response = await research_model.ainvoke(supervisor_messages)
    
    # Step 3: Update state and proceed to tool execution
    return Command(
        goto="supervisor_tools",
        update={
            "supervisor_messages": [response],
            "research_iterations": state.get("research_iterations", 0) + 1
        }
    )

async def supervisor_tools(
    state: SupervisorState,
    config: RunnableConfig,
) -> Command[Literal["supervisor", "__end__"]]:
    """Execute supervisor tools while isolating failures between research units."""
    configurable = Configuration.from_runnable_config(config)
    supervisor_messages = state.get("supervisor_messages", [])
    research_iterations = state.get("research_iterations", 0)

    if not supervisor_messages:
        error = _research_error(
            "supervisor",
            "missing_supervisor_message",
            "The supervisor had no message to process.",
            recoverable=False,
        )
        return Command(
            goto=END,
            update={
                "notes": {"type": "override", "value": []},
                "research_brief": state.get("research_brief", ""),
                "research_status": "failed",
                "research_errors": [error],
            },
        )

    most_recent_message = supervisor_messages[-1]
    tool_calls = list(getattr(most_recent_message, "tool_calls", []) or [])
    exceeded_allowed_iterations = (
        research_iterations > configurable.max_researcher_iterations
    )
    no_tool_calls = not tool_calls
    research_complete_tool_call = any(
        tool_call.get("name") == "ResearchComplete" for tool_call in tool_calls
    )

    if exceeded_allowed_iterations or no_tool_calls or research_complete_tool_call:
        existing_notes = state.get("notes", [])
        if not existing_notes:
            existing_notes = get_notes_from_tool_calls(supervisor_messages)
        notes = _valid_research_notes(existing_notes)
        evidence_records = _valid_evidence_records(
            state.get("evidence_records", [])
        )
        evidence_count = len(evidence_records)
        failed_units = int(state.get("failed_research_units", 0))
        existing_errors = state.get("research_errors", [])
        terminal_errors: list[ResearchError] = []

        if not notes or evidence_count < 1:
            status: ResearchStatus = "failed"
            if exceeded_allowed_iterations:
                code = "research_iteration_limit"
                message = "Research ended at the iteration limit without valid evidence."
            elif research_complete_tool_call:
                code = "research_completed_without_evidence"
                message = "ResearchComplete was called before valid evidence was collected."
            else:
                code = "supervisor_stopped_without_evidence"
                message = "The supervisor stopped without collecting valid evidence."
            terminal_errors.append(
                _research_error(
                    "supervisor",
                    code,
                    message,
                    recoverable=False,
                )
            )
        elif failed_units or existing_errors:
            status = "partial"
        else:
            status = "success"

        update: dict[str, Any] = {
            "notes": {"type": "override", "value": notes},
            "research_brief": state.get("research_brief", ""),
            "research_status": status,
        }
        if terminal_errors:
            update["research_errors"] = terminal_errors
        return Command(goto=END, update=update)

    all_tool_messages: list[ToolMessage] = []
    notes_delta: list[str] = []
    raw_notes_delta: list[str] = []
    errors_delta: list[ResearchError] = []
    evidence_records_delta: list[ResearchEvidence] = []
    evidence_delta = 0
    successful_units_delta = 0
    failed_units_delta = 0

    think_tool_calls = [
        tool_call for tool_call in tool_calls if tool_call.get("name") == "think_tool"
    ]
    for index, tool_call in enumerate(think_tool_calls):
        tool_call_id = str(tool_call.get("id") or f"think-tool-{index}")
        reflection = (tool_call.get("args") or {}).get("reflection")
        if not isinstance(reflection, str) or not reflection.strip():
            error = _research_error(
                "tool",
                "invalid_tool_arguments",
                "think_tool requires a non-empty reflection argument.",
                recoverable=True,
                tool_name="think_tool",
                tool_call_id=tool_call_id,
            )
            errors_delta.append(error)
            failed_units_delta += 1
            content = _tool_error_content(error)
        else:
            content = f"Reflection recorded: {reflection}"
        all_tool_messages.append(
            ToolMessage(
                content=content,
                name="think_tool",
                tool_call_id=tool_call_id,
            )
        )

    conduct_research_calls = [
        tool_call
        for tool_call in tool_calls
        if tool_call.get("name") == "ConductResearch"
    ]
    allowed_calls = conduct_research_calls[
        : configurable.max_concurrent_research_units
    ]
    overflow_calls = conduct_research_calls[
        configurable.max_concurrent_research_units :
    ]

    scheduled_calls: list[dict[str, Any]] = []
    research_tasks = []
    for index, tool_call in enumerate(allowed_calls):
        tool_call_id = str(tool_call.get("id") or f"research-unit-{index}")
        topic = (tool_call.get("args") or {}).get("research_topic")
        if not isinstance(topic, str) or not topic.strip():
            error = _research_error(
                "supervisor",
                "invalid_research_topic",
                "ConductResearch requires a non-empty research_topic argument.",
                recoverable=True,
                tool_name="ConductResearch",
                tool_call_id=tool_call_id,
            )
            errors_delta.append(error)
            failed_units_delta += 1
            all_tool_messages.append(
                ToolMessage(
                    content=_tool_error_content(error),
                    name="ConductResearch",
                    tool_call_id=tool_call_id,
                )
            )
            continue
        scheduled_calls.append(tool_call)
        research_tasks.append(
            researcher_subgraph.ainvoke(
                {
                    "researcher_messages": [HumanMessage(content=topic)],
                    "research_topic": topic,
                },
                config,
            )
        )

    tool_results = await asyncio.gather(*research_tasks, return_exceptions=True)
    for observation, tool_call in zip(tool_results, scheduled_calls):
        tool_call_id = str(tool_call.get("id") or "research-unit")
        topic = str((tool_call.get("args") or {}).get("research_topic") or "")

        if isinstance(observation, BaseException):
            code = (
                "researcher_token_limit"
                if is_token_limit_exceeded(observation, configurable.research_model)
                else "researcher_execution_failed"
            )
            error = _research_error(
                "researcher",
                code,
                f"{type(observation).__name__}: {observation}",
                recoverable=True,
                research_topic=topic,
                tool_name="ConductResearch",
                tool_call_id=tool_call_id,
            )
            errors_delta.append(error)
            failed_units_delta += 1
            all_tool_messages.append(
                ToolMessage(
                    content=_tool_error_content(error),
                    name="ConductResearch",
                    tool_call_id=tool_call_id,
                )
            )
            continue

        if hasattr(observation, "model_dump"):
            observation = observation.model_dump()
        if not isinstance(observation, dict):
            error = _research_error(
                "researcher",
                "invalid_researcher_output",
                "The researcher returned a non-object result.",
                recoverable=True,
                research_topic=topic,
                tool_name="ConductResearch",
                tool_call_id=tool_call_id,
            )
            errors_delta.append(error)
            failed_units_delta += 1
            all_tool_messages.append(
                ToolMessage(
                    content=_tool_error_content(error),
                    name="ConductResearch",
                    tool_call_id=tool_call_id,
                )
            )
            continue

        compressed_research = _content_text(
            observation.get("compressed_research", "")
        )
        unit_records = _valid_evidence_records(
            observation.get("evidence_records", [])
        )
        unit_evidence = len(unit_records)
        unit_errors = [
            error
            for error in observation.get("research_errors", [])
            if isinstance(error, dict)
        ]
        unit_status = observation.get("research_status")
        usable_result = (
            unit_evidence > 0
            and _is_valid_evidence_content(compressed_research)
        )

        errors_delta.extend(unit_errors)
        if usable_result:
            successful_units_delta += 1
            evidence_delta += unit_evidence
            evidence_records_delta.extend(unit_records)
            notes_delta.append(compressed_research)
            raw_notes_delta.extend(
                _valid_research_notes(observation.get("raw_notes", []))
            )
            tool_content = compressed_research
        else:
            if not unit_errors:
                unit_errors = [
                    _research_error(
                        "researcher",
                        "no_usable_research_output",
                        "The researcher returned no valid evidence.",
                        recoverable=True,
                        research_topic=topic,
                        tool_name="ConductResearch",
                        tool_call_id=tool_call_id,
                    )
                ]
                errors_delta.extend(unit_errors)
            tool_content = _tool_error_content(unit_errors[0])

        if not usable_result or unit_status in {"partial", "failed"}:
            failed_units_delta += 1

        all_tool_messages.append(
            ToolMessage(
                content=tool_content,
                name="ConductResearch",
                tool_call_id=tool_call_id,
            )
        )

    for index, overflow_call in enumerate(overflow_calls):
        tool_call_id = str(overflow_call.get("id") or f"overflow-{index}")
        error = _research_error(
            "supervisor",
            "concurrency_limit",
            (
                "Research unit was not run because the request exceeded "
                f"max_concurrent_research_units={configurable.max_concurrent_research_units}."
            ),
            recoverable=True,
            research_topic=str(
                (overflow_call.get("args") or {}).get("research_topic") or ""
            ),
            tool_name="ConductResearch",
            tool_call_id=tool_call_id,
        )
        errors_delta.append(error)
        failed_units_delta += 1
        all_tool_messages.append(
            ToolMessage(
                content=_tool_error_content(error),
                name="ConductResearch",
                tool_call_id=tool_call_id,
            )
        )

    known_tool_names = {"think_tool", "ConductResearch", "ResearchComplete"}
    for index, tool_call in enumerate(tool_calls):
        tool_name = str(tool_call.get("name") or "unknown")
        if tool_name in known_tool_names:
            continue
        tool_call_id = str(tool_call.get("id") or f"unknown-tool-{index}")
        error = _research_error(
            "supervisor",
            "unknown_supervisor_tool",
            f"Supervisor requested unavailable tool {tool_name!r}.",
            recoverable=True,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        errors_delta.append(error)
        failed_units_delta += 1
        all_tool_messages.append(
            ToolMessage(
                content=_tool_error_content(error),
                name=tool_name,
                tool_call_id=tool_call_id,
            )
        )

    total_successful_units = (
        int(state.get("successful_research_units", 0))
        + successful_units_delta
    )
    total_failed_units = (
        int(state.get("failed_research_units", 0)) + failed_units_delta
    )
    interim_status: ResearchStatus
    if total_successful_units and total_failed_units:
        interim_status = "partial"
    elif total_successful_units:
        interim_status = "success"
    else:
        interim_status = "failed"

    update_payload: dict[str, Any] = {
        "supervisor_messages": all_tool_messages,
        "research_status": interim_status,
        "evidence_count": evidence_delta,
        "successful_research_units": successful_units_delta,
        "failed_research_units": failed_units_delta,
    }
    if notes_delta:
        update_payload["notes"] = notes_delta
    if evidence_records_delta:
        update_payload["evidence_records"] = evidence_records_delta
    if raw_notes_delta:
        update_payload["raw_notes"] = ["\n".join(raw_notes_delta)]
    if errors_delta:
        update_payload["research_errors"] = errors_delta

    return Command(goto="supervisor", update=update_payload)

# Supervisor Subgraph Construction
# Creates the supervisor workflow that manages research delegation and coordination
supervisor_builder = StateGraph(SupervisorState, config_schema=Configuration)

# Add supervisor nodes for research management
supervisor_builder.add_node("supervisor", supervisor)           # Main supervisor logic
supervisor_builder.add_node("supervisor_tools", supervisor_tools)  # Tool execution handler

# Define supervisor workflow edges
supervisor_builder.add_edge(START, "supervisor")  # Entry point to supervisor

# Compile supervisor subgraph for use in main workflow
supervisor_subgraph = supervisor_builder.compile()

async def researcher(
    state: ResearcherState,
    config: RunnableConfig,
) -> Command[Literal["researcher_tools", "compress_research"]]:
    """Individual researcher that conducts focused research on specific topics.
    
    This researcher is given a specific research topic by the supervisor and uses
    available tools (search, think_tool, MCP tools) to gather comprehensive information.
    It can use think_tool for strategic planning between searches.
    
    Args:
        state: Current researcher state with messages and topic context
        config: Runtime configuration with model settings and tool availability
        
    Returns:
        Command to proceed to researcher_tools for tool execution
    """
    # Step 1: Load configuration and validate tool availability
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    
    # Get all available research tools (search, MCP, think_tool)
    tools = await get_all_tools(config)
    if len(tools) == 0:
        error = _research_error(
            "researcher",
            "no_research_tools",
            (
                "No tools are configured. Configure a search API or MCP tools "
                "before conducting research."
            ),
            recoverable=False,
            research_topic=state.get("research_topic", ""),
        )
        return Command(
            goto="compress_research",
            update={"research_errors": [error], "research_status": "failed"},
        )
    
    # Step 2: Configure the researcher model with tools
    research_model_config = {
        "model": configurable.research_model,
        "max_tokens": configurable.research_model_max_tokens,
        "api_key": get_api_key_for_model(configurable.research_model, config),
        "base_url": get_base_url_for_model(configurable.research_model, config),
        "tags": ["langsmith:nostream"]
    }
    
    # Prepare system prompt with MCP context if available
    researcher_prompt = research_system_prompt.format(
        mcp_prompt=configurable.mcp_prompt or "", 
        date=get_today_str()
    )
    
    # Configure model with tools, retry logic, and settings
    research_model = (
        configurable_model
        .bind_tools(tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
        .with_config(research_model_config)
    )
    
    # Step 3: Generate researcher response with system context
    messages = [SystemMessage(content=researcher_prompt)] + researcher_messages
    response = await research_model.ainvoke(messages)
    
    # Step 4: Update state and proceed to tool execution
    return Command(
        goto="researcher_tools",
        update={
            "researcher_messages": [response],
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1
        }
    )

# Tool Execution Helper Function
async def execute_tool_safely(
    tool,
    args,
    config,
    *,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
):
    """Execute one tool and convert exceptions to a structured Tool Error."""
    try:
        return await tool.ainvoke(args, config)
    except Exception as exc:
        error = _research_error(
            "tool",
            "tool_execution_failed",
            f"{type(exc).__name__}: {exc}",
            recoverable=True,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        return _tool_error_content(error)


async def researcher_tools(
    state: ResearcherState,
    config: RunnableConfig,
) -> Command[Literal["researcher", "compress_research"]]:
    """Execute researcher tools and preserve successful evidence beside failures."""
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    if not researcher_messages:
        error = _research_error(
            "researcher",
            "missing_researcher_message",
            "The researcher had no message to process.",
            recoverable=False,
            research_topic=state.get("research_topic", ""),
        )
        return Command(
            goto="compress_research",
            update={"research_status": "failed", "research_errors": [error]},
        )

    most_recent_message = researcher_messages[-1]
    tool_calls = list(getattr(most_recent_message, "tool_calls", []) or [])
    has_native_search = (
        openai_websearch_called(most_recent_message)
        or anthropic_websearch_called(most_recent_message)
    )

    if not tool_calls:
        update: dict[str, Any] = {}
        content = _content_text(most_recent_message.content)
        message_id = str(getattr(most_recent_message, "id", "") or "")
        native_call_id = message_id or (
            f"native-search-{_content_hash(content)[:16]}"
        )
        native_record = (
            _make_evidence_record(
                source="native_search",
                tool_name="native_web_search",
                tool_call_id=native_call_id,
                value=content,
            )
            if has_native_search
            else None
        )
        if native_record:
            update = {
                "evidence_count": 1,
                "evidence_records": [native_record],
                "research_status": "success",
            }
        elif not _valid_evidence_records(
            state.get("evidence_records", [])
        ):
            error = _research_error(
                "researcher",
                "researcher_stopped_without_evidence",
                "The researcher stopped before collecting valid evidence.",
                recoverable=True,
                research_topic=state.get("research_topic", ""),
            )
            update = {"research_status": "failed", "research_errors": [error]}
        return Command(goto="compress_research", update=update)

    tools = await get_all_tools(config)
    tools_by_name = {
        tool.name if hasattr(tool, "name") else tool.get("name", "web_search"): tool
        for tool in tools
    }

    async def execute_call(tool_call: dict[str, Any]):
        tool_name = str(tool_call.get("name") or "unknown")
        tool_call_id = str(tool_call.get("id") or "unknown-tool-call")
        if tool_name == "ResearchComplete":
            return "Research marked complete."
        tool = tools_by_name.get(tool_name)
        if tool is None:
            error = _research_error(
                "tool",
                "unknown_tool",
                f"Researcher requested unavailable tool {tool_name!r}.",
                recoverable=True,
                research_topic=state.get("research_topic", ""),
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
            return _tool_error_content(error)
        return await execute_tool_safely(
            tool,
            tool_call.get("args") or {},
            config,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )

    observations = await asyncio.gather(
        *(execute_call(tool_call) for tool_call in tool_calls),
        return_exceptions=True,
    )
    tool_outputs: list[ToolMessage] = []
    errors_delta: list[ResearchError] = []
    evidence_records_delta: list[ResearchEvidence] = []
    evidence_delta = 0

    for index, (observation, tool_call) in enumerate(
        zip(observations, tool_calls)
    ):
        tool_name = str(tool_call.get("name") or "unknown")
        tool_call_id = str(tool_call.get("id") or f"tool-call-{index}")
        if isinstance(observation, BaseException):
            error = _research_error(
                "tool",
                "tool_execution_failed",
                f"{type(observation).__name__}: {observation}",
                recoverable=True,
                research_topic=state.get("research_topic", ""),
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
            observation = _tool_error_content(error)

        error = _parse_tool_error(observation)
        if error:
            errors_delta.append(error)
        elif tool_name not in {"think_tool", "ResearchComplete"}:
            record = _make_evidence_record(
                source="tool",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                value=observation,
            )
            if record:
                evidence_records_delta.append(record)

        tool_outputs.append(
            ToolMessage(
                content=_content_text(observation),
                name=tool_name,
                tool_call_id=tool_call_id,
            )
        )

    evidence_delta = len(evidence_records_delta)
    total_evidence = len(
        _valid_evidence_records(state.get("evidence_records", []))
    ) + evidence_delta
    has_errors = bool(state.get("research_errors", [])) or bool(errors_delta)
    if total_evidence and has_errors:
        interim_status: ResearchStatus = "partial"
    elif total_evidence:
        interim_status = "success"
    else:
        interim_status = "failed"

    update_payload: dict[str, Any] = {
        "researcher_messages": tool_outputs,
        "evidence_count": evidence_delta,
        "research_status": interim_status,
    }
    if evidence_records_delta:
        update_payload["evidence_records"] = evidence_records_delta
    if errors_delta:
        update_payload["research_errors"] = errors_delta

    exceeded_iterations = (
        state.get("tool_call_iterations", 0)
        >= configurable.max_react_tool_calls
    )
    research_complete_called = any(
        tool_call.get("name") == "ResearchComplete" for tool_call in tool_calls
    )
    if exceeded_iterations or research_complete_called:
        return Command(goto="compress_research", update=update_payload)
    return Command(goto="researcher", update=update_payload)

async def compress_research(
    state: ResearcherState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Compress valid evidence or return a transparent degraded result."""
    researcher_messages = list(state.get("researcher_messages", []))
    evidence_records = _valid_evidence_records(
        state.get("evidence_records", [])
    )
    evidence_count = len(evidence_records)
    raw_evidence = _evidence_findings(evidence_records)

    if evidence_count < 1 or not raw_evidence:
        error = _research_error(
            "compression",
            "no_valid_evidence",
            "Compression was skipped because no valid research evidence exists.",
            recoverable=False,
            research_topic=state.get("research_topic", ""),
        )
        return {
            "compressed_research": "",
            "raw_notes": [],
            "research_status": "failed",
            "research_errors": [error],
        }

    configurable = Configuration.from_runnable_config(config)
    synthesizer_model = configurable_model.with_config(
        {
            "model": configurable.compression_model,
            "max_tokens": configurable.compression_model_max_tokens,
            "api_key": get_api_key_for_model(
                configurable.compression_model,
                config,
            ),
            "base_url": get_base_url_for_model(
                configurable.compression_model,
                config,
            ),
            "tags": ["langsmith:nostream"],
        }
    )
    researcher_messages.append(
        HumanMessage(content=compress_research_simple_human_message)
    )
    synthesis_attempts = 0
    max_attempts = 3
    last_error: Exception | None = None

    while synthesis_attempts < max_attempts:
        try:
            compression_prompt = compress_research_system_prompt.format(
                date=get_today_str()
            )
            messages = [
                SystemMessage(content=compression_prompt),
                *researcher_messages,
            ]
            response = await synthesizer_model.ainvoke(messages)
            compressed_research = _content_text(response.content)
            if compressed_research:
                status: ResearchStatus = (
                    "partial" if state.get("research_errors", []) else "success"
                )
                return {
                    "compressed_research": compressed_research,
                    "raw_notes": [raw_evidence],
                    "research_status": status,
                }
            last_error = ValueError("Compression model returned empty content.")
            break
        except Exception as exc:
            last_error = exc
            synthesis_attempts += 1
            if is_token_limit_exceeded(
                exc,
                configurable.compression_model,
            ):
                researcher_messages = remove_up_to_last_ai_message(
                    researcher_messages
                )
            continue

    error = _research_error(
        "compression",
        "compression_failed",
        (
            f"{type(last_error).__name__}: {last_error}"
            if last_error
            else "Compression failed after all retries."
        ),
        recoverable=True,
        research_topic=state.get("research_topic", ""),
    )
    return {
        "compressed_research": raw_evidence,
        "raw_notes": [raw_evidence],
        "research_status": "partial",
        "research_errors": [error],
    }

# Researcher Subgraph Construction
# Creates individual researcher workflow for conducting focused research on specific topics
researcher_builder = StateGraph(
    ResearcherState, 
    output=ResearcherOutputState, 
    config_schema=Configuration
)

# Add researcher nodes for research execution and compression
researcher_builder.add_node("researcher", researcher)                 # Main researcher logic
researcher_builder.add_node("researcher_tools", researcher_tools)     # Tool execution handler
researcher_builder.add_node("compress_research", compress_research)   # Research compression

# Define researcher workflow edges
researcher_builder.add_edge(START, "researcher")           # Entry point to researcher
researcher_builder.add_edge("compress_research", END)      # Exit point after compression

# Compile researcher subgraph for parallel execution by supervisor
researcher_subgraph = researcher_builder.compile()

async def final_report_generation(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Generate a report only when valid research evidence is available."""
    raw_evidence_records = state.get("evidence_records", [])
    evidence_records = _valid_evidence_records(raw_evidence_records)
    invalid_evidence_count = max(
        0,
        len(raw_evidence_records) - len(evidence_records),
    )
    cleared_state = {"notes": {"type": "override", "value": []}}

    if not evidence_records:
        error = _research_error(
            "writer",
            "no_valid_evidence",
            (
                "Writer refused to generate a report because no valid, "
                "hash-verified evidence records exist."
            ),
            recoverable=False,
        )
        failure_message = (
            "Research failed: no valid research evidence was collected, "
            "so no final report was generated."
        )
        return {
            "final_report": failure_message,
            "messages": [AIMessage(content=failure_message)],
            "research_status": "failed",
            "research_errors": [error],
            **cleared_state,
        }

    findings = _evidence_findings(evidence_records)
    evidence_validation_errors: list[ResearchError] = []
    if invalid_evidence_count:
        evidence_validation_errors.append(
            _research_error(
                "writer",
                "invalid_evidence_records",
                (
                    f"Writer rejected {invalid_evidence_count} evidence "
                    "record(s) with invalid provenance or hashes."
                ),
                recoverable=False,
            )
        )

    incoming_status = state.get("research_status")
    if (
        incoming_status == "success"
        and not evidence_validation_errors
    ):
        completed_status: ResearchStatus = "success"
    else:
        completed_status = "partial"

    configurable = Configuration.from_runnable_config(config)
    writer_model_config = {
        "model": configurable.final_report_model,
        "max_tokens": configurable.final_report_model_max_tokens,
        "api_key": get_api_key_for_model(
            configurable.final_report_model,
            config,
        ),
        "base_url": get_base_url_for_model(
            configurable.final_report_model,
            config,
        ),
        "tags": ["langsmith:nostream"],
    }

    def writer_failure(
        code: str,
        error_message: str,
        user_message: str,
    ) -> dict[str, Any]:
        error = _research_error(
            "writer",
            code,
            error_message,
            recoverable=True,
        )
        return {
            "final_report": f"Error generating final report: {error_message}",
            "messages": [AIMessage(content=user_message)],
            "research_status": "partial",
            "research_errors": [*evidence_validation_errors, error],
            **cleared_state,
        }

    max_retries = 3
    current_retry = 0
    findings_token_limit: int | None = None

    while current_retry <= max_retries:
        try:
            final_report_prompt = final_report_generation_prompt.format(
                research_brief=state.get("research_brief", ""),
                messages=get_buffer_string(state.get("messages", [])),
                findings=findings,
                date=get_today_str(),
            )
            final_report = await configurable_model.with_config(
                writer_model_config
            ).ainvoke([HumanMessage(content=final_report_prompt)])
            report_content = _content_text(final_report.content)
            if not report_content:
                return writer_failure(
                    "empty_writer_response",
                    "The Writer returned empty content.",
                    "Report generation returned no content.",
                )
            result: dict[str, Any] = {
                "final_report": report_content,
                "messages": [final_report],
                "research_status": completed_status,
                **cleared_state,
            }
            if evidence_validation_errors:
                result["research_errors"] = evidence_validation_errors
            return result
        except Exception as exc:
            if not is_token_limit_exceeded(
                exc,
                configurable.final_report_model,
            ):
                return writer_failure(
                    "writer_execution_failed",
                    f"{type(exc).__name__}: {exc}",
                    "Report generation failed, but collected evidence was preserved.",
                )

            current_retry += 1
            if current_retry == 1:
                model_token_limit = get_model_token_limit(
                    configurable.final_report_model
                )
                if not model_token_limit:
                    return writer_failure(
                        "unknown_writer_token_limit",
                        (
                            "Token limit exceeded and the model context limit "
                            f"is unknown: {exc}"
                        ),
                        "Report generation stopped because the model context limit is unknown.",
                    )
                findings_token_limit = model_token_limit * 4
            else:
                findings_token_limit = int(
                    (findings_token_limit or len(findings)) * 0.9
                )
            findings = findings[:findings_token_limit]

    return writer_failure(
        "writer_retries_exhausted",
        "Maximum retries exceeded.",
        "Report generation failed after maximum retries.",
    )

# Main Deep Researcher Graph Construction
# Creates the complete deep research workflow from user input to final report
deep_researcher_builder = StateGraph(
    AgentState, 
    input=AgentInputState, 
    config_schema=Configuration
)

# Add main workflow nodes for the complete research process
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)           # User clarification phase
deep_researcher_builder.add_node("write_research_brief", write_research_brief)     # Research planning phase
deep_researcher_builder.add_node("research_supervisor", supervisor_subgraph)       # Research execution phase
deep_researcher_builder.add_node("final_report_generation", final_report_generation)  # Report generation phase

# Define main workflow edges for sequential execution
deep_researcher_builder.add_edge(START, "clarify_with_user")                       # Entry point
deep_researcher_builder.add_edge("research_supervisor", "final_report_generation") # Research to report
deep_researcher_builder.add_edge("final_report_generation", END)                   # Final exit point

# Compile the complete deep researcher workflow
deep_researcher = deep_researcher_builder.compile()