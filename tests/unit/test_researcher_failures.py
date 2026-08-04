import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import open_deep_research.deep_researcher as researcher_module
from scripts.run_baseline import EventMetrics, resolve_run_status


def _configuration(**overrides):
    values = {
        "max_concurrent_research_units": 2,
        "max_researcher_iterations": 3,
        "max_react_tool_calls": 2,
        "research_model": "openai:test-model",
        "compression_model": "openai:test-compression-model",
        "compression_model_max_tokens": 4096,
        "final_report_model": "openai:test-writer-model",
        "final_report_model_max_tokens": 4096,
        "openai_base_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _tool_call(name, tool_call_id, **args):
    return {
        "name": name,
        "args": args,
        "id": tool_call_id,
        "type": "tool_call",
    }


@pytest.mark.asyncio
async def test_parallel_researcher_failure_preserves_success(
    monkeypatch,
):
    class FakeResearcherSubgraph:
        async def ainvoke(self, payload, config):
            del config
            topic = payload["research_topic"]
            if topic == "failing topic":
                raise RuntimeError("research backend unavailable")
            evidence_record = researcher_module._make_evidence_record(
                source="tool",
                tool_name="healthy_search",
                tool_call_id="healthy-tool-call",
                value="healthy raw evidence",
            )
            assert evidence_record is not None
            return {
                "compressed_research": "Verified evidence from the healthy unit.",
                "raw_notes": ["healthy raw evidence"],
                "research_status": "success",
                "research_errors": [],
                "evidence_count": 1,
                "evidence_records": [evidence_record],
            }

    monkeypatch.setattr(
        researcher_module,
        "Configuration",
        SimpleNamespace(
            from_runnable_config=lambda config: _configuration()
        ),
    )
    monkeypatch.setattr(
        researcher_module,
        "researcher_subgraph",
        FakeResearcherSubgraph(),
    )
    state = {
        "supervisor_messages": [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "ConductResearch",
                        "healthy-call",
                        research_topic="healthy topic",
                    ),
                    _tool_call(
                        "ConductResearch",
                        "failing-call",
                        research_topic="failing topic",
                    ),
                ],
            )
        ],
        "research_brief": "brief",
        "research_iterations": 1,
    }

    command = await researcher_module.supervisor_tools(state, {})

    assert command.goto == "supervisor"
    assert command.update["research_status"] == "partial"
    assert command.update["evidence_count"] == 1
    assert len(command.update["evidence_records"]) == 1
    assert command.update["evidence_records"][0]["tool_name"] == "healthy_search"
    assert command.update["successful_research_units"] == 1
    assert command.update["failed_research_units"] == 1
    assert command.update["notes"] == [
        "Verified evidence from the healthy unit."
    ]
    tool_messages = command.update["supervisor_messages"]
    assert len(tool_messages) == 2
    failed_message = next(
        message
        for message in tool_messages
        if message.tool_call_id == "failing-call"
    )
    payload = json.loads(failed_message.content)
    assert payload["type"] == "tool_error"
    assert payload["error"]["code"] == "researcher_execution_failed"


@pytest.mark.asyncio
async def test_unknown_supervisor_tool_returns_structured_error(
    monkeypatch,
):
    monkeypatch.setattr(
        researcher_module,
        "Configuration",
        SimpleNamespace(
            from_runnable_config=lambda config: _configuration()
        ),
    )
    state = {
        "supervisor_messages": [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "invented_supervisor_tool",
                        "unknown-supervisor-call",
                    )
                ],
            )
        ],
        "research_brief": "brief",
        "research_iterations": 1,
    }

    command = await researcher_module.supervisor_tools(state, {})

    assert command.goto == "supervisor"
    assert command.update["research_status"] == "failed"
    assert command.update["evidence_count"] == 0
    assert command.update["successful_research_units"] == 0
    assert command.update["failed_research_units"] == 1
    assert "evidence_records" not in command.update
    error = command.update["research_errors"][0]
    assert error["code"] == "unknown_supervisor_tool"
    tool_message = command.update["supervisor_messages"][0]
    assert isinstance(tool_message, ToolMessage)
    payload = json.loads(tool_message.content)
    assert payload["type"] == "tool_error"
    assert payload["error"]["code"] == "unknown_supervisor_tool"


@pytest.mark.asyncio
async def test_unknown_researcher_tool_returns_structured_error(
    monkeypatch,
):
    async def no_tools(config):
        del config
        return []

    monkeypatch.setattr(
        researcher_module,
        "Configuration",
        SimpleNamespace(
            from_runnable_config=lambda config: _configuration()
        ),
    )
    monkeypatch.setattr(researcher_module, "get_all_tools", no_tools)
    state = {
        "researcher_messages": [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "invented_search",
                        "unknown-call",
                        query="test",
                    )
                ],
            )
        ],
        "research_topic": "topic",
        "tool_call_iterations": 0,
    }

    command = await researcher_module.researcher_tools(state, {})

    assert command.update["research_status"] == "failed"
    assert command.update["evidence_count"] == 0
    assert command.update["research_errors"][0]["code"] == "unknown_tool"
    tool_message = command.update["researcher_messages"][0]
    assert isinstance(tool_message, ToolMessage)
    payload = json.loads(tool_message.content)
    assert payload == {
        "error": {
            "code": "unknown_tool",
            "message": "Researcher requested unavailable tool 'invented_search'.",
            "recoverable": True,
            "research_topic": "topic",
            "stage": "tool",
            "tool_call_id": "unknown-call",
            "tool_name": "invented_search",
        },
        "type": "tool_error",
    }


@pytest.mark.asyncio
async def test_researcher_records_only_successful_tool_output(
    monkeypatch,
):
    class FakeTool:
        def __init__(self, name, *, result=None, error=None):
            self.name = name
            self.result = result
            self.error = error

        async def ainvoke(self, args, config):
            del args, config
            if self.error:
                raise self.error
            return self.result

    async def fake_tools(config):
        del config
        return [
            FakeTool("healthy_search", result="verified tool evidence"),
            FakeTool(
                "broken_search",
                error=RuntimeError("search backend unavailable"),
            ),
        ]

    monkeypatch.setattr(
        researcher_module,
        "Configuration",
        SimpleNamespace(
            from_runnable_config=lambda config: _configuration()
        ),
    )
    monkeypatch.setattr(researcher_module, "get_all_tools", fake_tools)
    state = {
        "researcher_messages": [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call("healthy_search", "healthy-search-call"),
                    _tool_call("broken_search", "broken-search-call"),
                ],
            )
        ],
        "research_topic": "topic",
        "tool_call_iterations": 0,
    }

    command = await researcher_module.researcher_tools(state, {})

    assert command.goto == "researcher"
    assert command.update["research_status"] == "partial"
    assert command.update["evidence_count"] == 1
    assert len(command.update["evidence_records"]) == 1
    record = command.update["evidence_records"][0]
    assert record["tool_name"] == "healthy_search"
    assert record["tool_call_id"] == "healthy-search-call"
    assert record["content"] == "verified tool evidence"
    assert record["content_hash"] == researcher_module._content_hash(
        record["content"]
    )
    assert record["evidence_id"] == researcher_module._evidence_id(
        "tool",
        record["tool_name"],
        record["tool_call_id"],
        record["content_hash"],
    )
    assert command.update["research_errors"][0]["code"] == (
        "tool_execution_failed"
    )


@pytest.mark.asyncio
async def test_all_researchers_fail_and_writer_refuses_without_model_call(
    monkeypatch,
):
    class FailedResearcherSubgraph:
        async def ainvoke(self, payload, config):
            del payload, config
            raise RuntimeError("all units failed")

    class ExplodingWriter:
        def with_config(self, config):
            del config
            raise AssertionError("Writer must not be configured without evidence")

    monkeypatch.setattr(
        researcher_module,
        "Configuration",
        SimpleNamespace(
            from_runnable_config=lambda config: _configuration()
        ),
    )
    monkeypatch.setattr(
        researcher_module,
        "researcher_subgraph",
        FailedResearcherSubgraph(),
    )
    supervisor_state = {
        "supervisor_messages": [
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call(
                        "ConductResearch",
                        "failed-call",
                        research_topic="failing topic",
                    )
                ],
            )
        ],
        "research_brief": "brief",
        "research_iterations": 1,
    }

    supervisor_command = await researcher_module.supervisor_tools(
        supervisor_state,
        {},
    )

    assert supervisor_command.update["research_status"] == "failed"
    assert supervisor_command.update["evidence_count"] == 0
    assert "notes" not in supervisor_command.update

    monkeypatch.setattr(
        researcher_module,
        "configurable_model",
        ExplodingWriter(),
    )
    writer_result = await researcher_module.final_report_generation(
        {
            "messages": [],
            "notes": [],
            "evidence_count": 0,
            "research_status": "failed",
            "research_errors": supervisor_command.update[
                "research_errors"
            ],
        },
        {},
    )

    assert writer_result["research_status"] == "failed"
    assert writer_result["research_errors"][0]["code"] == "no_valid_evidence"
    assert writer_result["final_report"].startswith("Research failed:")
    assert "comprehensive" not in writer_result["final_report"].lower()


@pytest.mark.asyncio
async def test_writer_rejects_error_placeholders_as_evidence(
    monkeypatch,
):
    class ExplodingWriter:
        def with_config(self, config):
            del config
            raise AssertionError("Error placeholders are not evidence")

    error_content = researcher_module._tool_error_content(
        researcher_module._research_error(
            "tool",
            "unknown_tool",
            "missing",
            recoverable=True,
        )
    )
    monkeypatch.setattr(
        researcher_module,
        "configurable_model",
        ExplodingWriter(),
    )

    result = await researcher_module.final_report_generation(
        {
            "messages": [],
            "notes": [error_content],
            "evidence_count": 1,
            "research_status": "partial",
        },
        {},
    )

    assert result["research_status"] == "failed"
    assert result["research_errors"][0]["code"] == "no_valid_evidence"


@pytest.mark.asyncio
async def test_writer_rejects_notes_and_count_without_records(
    monkeypatch,
):
    class ExplodingWriter:
        def with_config(self, config):
            del config
            raise AssertionError("Unverified notes must not reach the Writer")

    monkeypatch.setattr(
        researcher_module,
        "configurable_model",
        ExplodingWriter(),
    )

    result = await researcher_module.final_report_generation(
        {
            "messages": [],
            "notes": ["ordinary but unverified research note"],
            "evidence_count": 12,
            "research_status": "success",
        },
        {},
    )

    assert result["research_status"] == "failed"
    assert result["research_errors"][0]["code"] == "no_valid_evidence"


@pytest.mark.asyncio
async def test_writer_rejects_tampered_evidence_hash(
    monkeypatch,
):
    class ExplodingWriter:
        def with_config(self, config):
            del config
            raise AssertionError("Tampered evidence must not reach the Writer")

    valid_record = researcher_module._make_evidence_record(
        source="tool",
        tool_name="paper_search",
        tool_call_id="paper-search-call",
        value="original evidence",
    )
    assert valid_record is not None
    tampered_record = {**valid_record, "content": "tampered evidence"}
    monkeypatch.setattr(
        researcher_module,
        "configurable_model",
        ExplodingWriter(),
    )

    result = await researcher_module.final_report_generation(
        {
            "messages": [],
            "evidence_records": [tampered_record],
            "evidence_count": 1,
            "research_status": "success",
        },
        {},
    )

    assert result["research_status"] == "failed"
    assert result["research_errors"][0]["code"] == "no_valid_evidence"


@pytest.mark.asyncio
async def test_compression_rejects_messages_and_count_without_records():
    result = await researcher_module.compress_research(
        {
            "researcher_messages": [
                ToolMessage(
                    content="legacy unverified output",
                    name="paper_search",
                    tool_call_id="legacy-call",
                )
            ],
            "research_topic": "topic",
            "evidence_count": 1,
        },
        {},
    )

    assert result["research_status"] == "failed"
    assert result["compressed_research"] == ""
    assert result["research_errors"][0]["code"] == "no_valid_evidence"


@pytest.mark.asyncio
async def test_compression_uses_hash_verified_records_and_output_keeps_them(
    monkeypatch,
):
    class FakeCompressor:
        def with_config(self, config):
            del config
            return self

        async def ainvoke(self, messages):
            del messages
            return AIMessage(content="compressed verified evidence")

    evidence_record = researcher_module._make_evidence_record(
        source="tool",
        tool_name="paper_search",
        tool_call_id="paper-search-call",
        value="verified paper evidence",
    )
    assert evidence_record is not None
    monkeypatch.setattr(
        researcher_module,
        "Configuration",
        SimpleNamespace(
            from_runnable_config=lambda config: _configuration()
        ),
    )
    monkeypatch.setattr(
        researcher_module,
        "configurable_model",
        FakeCompressor(),
    )

    result = await researcher_module.compress_research(
        {
            "researcher_messages": [],
            "research_topic": "topic",
            "evidence_records": [evidence_record],
            "evidence_count": 1,
        },
        {},
    )

    assert result["research_status"] == "success"
    assert result["compressed_research"] == "compressed verified evidence"
    assert evidence_record["evidence_id"] in result["raw_notes"][0]
    output = researcher_module.ResearcherOutputState.model_validate(
        {
            **result,
            "evidence_count": 1,
            "evidence_records": [evidence_record],
        }
    )
    assert output.evidence_records == [evidence_record]


def test_runner_serializes_partial_and_failed_states():
    partial_state = {
        "final_report": "A report based on the surviving evidence.",
        "research_status": "partial",
        "research_errors": [
            {
                "stage": "researcher",
                "code": "researcher_execution_failed",
                "message": "one unit failed",
                "recoverable": True,
            }
        ],
        "evidence_count": 1,
    }
    status, error = resolve_run_status(partial_state, None, [])

    assert status == "partial"
    assert "researcher_execution_failed" in error
    serialized = json.loads(
        json.dumps(
            {
                "status": status,
                "research_errors": partial_state["research_errors"],
            }
        )
    )
    assert serialized["status"] == "partial"

    failed_status, failed_error = resolve_run_status(
        {
            "final_report": "Research failed: no evidence.",
            "research_status": "failed",
            "research_errors": [],
            "evidence_count": 0,
        },
        None,
        [],
    )
    assert failed_status == "failed"
    assert failed_error == "Research completed with status failed."

    metrics = EventMetrics(final_state=partial_state)
    metrics_payload = metrics.as_dict(duration_ms=1, sources_count=0)
    assert metrics_payload["degraded"] is True
    assert metrics_payload["research_status"] == "partial"
    assert metrics_payload["evidence_count"] == 1
