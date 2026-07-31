#!/usr/bin/env python3
"""Run repeatable ScholarMind baseline cases and append structured results."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evaluation/cases/baseline.jsonl"
DEFAULT_OUTPUT = ROOT / "evaluation/results/baseline-qwen3-local.jsonl"
SCHEMA_VERSION = "1.0.0"
CASE_ID_PATTERN = re.compile(r"^baseline-\d{3}$")
URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
GRAPH_NODES = {
    "clarify_with_user",
    "write_research_brief",
    "research_supervisor",
    "supervisor",
    "supervisor_tools",
    "researcher",
    "researcher_tools",
    "compress_research",
    "final_report_generation",
}
SEARCH_TOOL_MARKERS = ("search", "tavily", "exa", "arxiv", "linkup")


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load and validate stable JSONL evaluation cases."""
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            case = json.loads(raw_line)
            case_id = case.get("case_id")
            if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
                raise ValueError(f"{path}:{line_number}: invalid case_id {case_id!r}")
            if case_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate case_id {case_id}")
            question = case.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError(f"{path}:{line_number}: question must be non-empty")
            seen.add(case_id)
            cases.append(case)
    if not 8 <= len(cases) <= 10:
        raise ValueError(f"{path}: expected 8-10 cases, found {len(cases)}")
    return cases


def extract_source_urls(report: str) -> list[str]:
    """Extract unique HTTP(S) source URLs while preserving report order."""
    sources: list[str] = []
    seen: set[str] = set()
    for match in URL_PATTERN.findall(report):
        url = match.rstrip(".,;:!?，。；：！？")
        if url not in seen:
            seen.add(url)
            sources.append(url)
    return sources


def load_existing_records(path: Path) -> list[dict[str, Any]]:
    """Read valid existing result rows without modifying history."""
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                records.append(json.loads(raw_line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return records


def completed_case_ids(records: list[dict[str, Any]], run_id: str) -> set[str]:
    """Return cases already recorded for one run."""
    return {
        str(record["case_id"])
        for record in records
        if record.get("run_id") == run_id and record.get("case_id")
    }


def next_attempt(records: list[dict[str, Any]], run_id: str, case_id: str) -> int:
    """Return the next append-only attempt number."""
    attempts = [
        int(record.get("attempt", 1))
        for record in records
        if record.get("run_id") == run_id and record.get("case_id") == case_id
    ]
    return max(attempts, default=0) + 1


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append one durable JSONL record without rewriting previous rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def configure_local_no_proxy() -> None:
    """Bypass inherited proxies for project-local model endpoints."""
    required = ("127.0.0.1", "localhost", "::1")
    for variable in ("NO_PROXY", "no_proxy"):
        values = [
            value.strip()
            for value in os.getenv(variable, "").split(",")
            if value.strip()
        ]
        for value in required:
            if value not in values:
                values.append(value)
        os.environ[variable] = ",".join(values)


def read_vllm_token_counters() -> tuple[int, int] | None:
    """Read exact cumulative token counters from the local vLLM server."""
    base_url = os.getenv("OPENAI_BASE_URL", "http://[::1]:8000/v1")
    metrics_url = base_url.removesuffix("/v1").rstrip("/") + "/metrics"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(metrics_url, timeout=10) as response:
            body = response.read().decode()
    except (OSError, TimeoutError, urllib.error.URLError):
        return None
    prompt_tokens = 0.0
    generation_tokens = 0.0
    for line in body.splitlines():
        if line.startswith("vllm:prompt_tokens_total{"):
            prompt_tokens += float(line.rsplit(" ", 1)[-1])
        elif line.startswith("vllm:generation_tokens_total{"):
            generation_tokens += float(line.rsplit(" ", 1)[-1])
    return round(prompt_tokens), round(generation_tokens)


def _walk_ai_messages(value: Any, seen: set[int] | None = None):
    """Yield AI messages from common LangChain result containers."""
    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return
    seen.add(value_id)
    if isinstance(value, AIMessage):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_ai_messages(item, seen)
        return
    if isinstance(value, list | tuple):
        for item in value:
            yield from _walk_ai_messages(item, seen)
        return
    for attribute in ("message", "generations"):
        nested = getattr(value, attribute, None)
        if nested is not None:
            yield from _walk_ai_messages(nested, seen)


def _message_usage(message: AIMessage) -> tuple[int, int, int]:
    """Normalize token usage from OpenAI-compatible response metadata."""
    usage = message.usage_metadata or {}
    response_usage = (message.response_metadata or {}).get("token_usage") or {}
    input_tokens = int(
        usage.get("input_tokens")
        or response_usage.get("prompt_tokens")
        or response_usage.get("input_tokens")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or response_usage.get("completion_tokens")
        or response_usage.get("output_tokens")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or response_usage.get("total_tokens")
        or input_tokens + output_tokens
    )
    return input_tokens, output_tokens, total_tokens


@dataclass
class EventMetrics:
    """Aggregate LangGraph v2 stream events for one case."""

    graph_run_id: str | None = None
    final_state: dict[str, Any] = field(default_factory=dict)
    node_counts: Counter[str] = field(default_factory=Counter)
    node_duration_ms: dict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    node_started: dict[str, tuple[str, float]] = field(default_factory=dict)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: Counter[str] = field(default_factory=Counter)
    executed_tools: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def consume(self, event: dict[str, Any]) -> None:
        """Consume one `astream_events(version="v2")` event."""
        event_type = event.get("event", "")
        run_id = str(event.get("run_id", ""))
        name = str(event.get("name", ""))
        metadata = event.get("metadata") or {}
        node = metadata.get("langgraph_node")
        if event_type == "on_chain_start" and name in GRAPH_NODES:
            self.node_counts[name] += 1
            self.node_started[run_id] = (name, time.perf_counter())
        elif event_type == "on_chain_end":
            started = self.node_started.pop(run_id, None)
            if started:
                node_name, start_time = started
                self.node_duration_ms[node_name] += (
                    time.perf_counter() - start_time
                ) * 1000
            if not event.get("parent_ids"):
                self.graph_run_id = run_id or None
                output = (event.get("data") or {}).get("output")
                if isinstance(output, dict):
                    self.final_state = output
        elif event_type == "on_chat_model_end":
            self.llm_calls += 1
            output = (event.get("data") or {}).get("output")
            for message in _walk_ai_messages(output):
                input_tokens, output_tokens, total_tokens = _message_usage(message)
                self.input_tokens += input_tokens
                self.output_tokens += output_tokens
                self.total_tokens += total_tokens
                for tool_call in message.tool_calls or []:
                    self.tool_calls[str(tool_call.get("name", "unknown"))] += 1
        elif event_type == "on_tool_start":
            self.executed_tools[name or "unknown"] += 1
        elif event_type.endswith("_error"):
            error = (event.get("data") or {}).get("error")
            self.errors.append(f"{name or node or 'unknown'}: {error}")

    def as_dict(self, duration_ms: int, sources_count: int) -> dict[str, Any]:
        """Serialize collected metrics into the result schema."""
        requested_search_calls = sum(
            count
            for name, count in self.tool_calls.items()
            if name not in {"ConductResearch", "ResearchComplete", "think_tool"}
            and any(marker in name.lower() for marker in SEARCH_TOOL_MARKERS)
        )
        executed_search_calls = sum(
            count
            for name, count in self.executed_tools.items()
            if any(marker in name.lower() for marker in SEARCH_TOOL_MARKERS)
        )
        return {
            "duration_ms": duration_ms,
            "node_counts": dict(sorted(self.node_counts.items())),
            "node_duration_ms": {
                name: round(value)
                for name, value in sorted(self.node_duration_ms.items())
            },
            "llm_calls": self.llm_calls,
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "total": self.total_tokens,
            },
            "tool_calls": {
                "total": sum(self.tool_calls.values()),
                "search": executed_search_calls,
                "requested_search": requested_search_calls,
                "executed_total": sum(self.executed_tools.values()),
                "by_name": dict(sorted(self.tool_calls.items())),
                "executed_by_name": dict(sorted(self.executed_tools.items())),
            },
            "researcher_count": self.tool_calls.get("ConductResearch", 0),
            "compression_count": self.node_counts.get("compress_research", 0),
            "degraded": bool(self.errors)
            or self.node_counts.get("compress_research", 0)
            < self.tool_calls.get("ConductResearch", 0),
            "sources_count": sources_count,
            "event_errors": self.errors,
        }


def runtime_configuration(thread_id: str) -> dict[str, Any]:
    """Build an explicit, non-secret local baseline configuration."""
    model = os.getenv("RESEARCH_MODEL", "openai:qwen3-14b-local")
    return {
        "thread_id": thread_id,
        "allow_clarification": False,
        "search_api": os.getenv("SEARCH_API", "none"),
        "max_concurrent_research_units": int(
            os.getenv("MAX_CONCURRENT_RESEARCH_UNITS", "1")
        ),
        "max_researcher_iterations": int(
            os.getenv("MAX_RESEARCHER_ITERATIONS", "1")
        ),
        "max_react_tool_calls": int(os.getenv("MAX_REACT_TOOL_CALLS", "2")),
        "research_model": model,
        "summarization_model": os.getenv("SUMMARIZATION_MODEL", model),
        "compression_model": os.getenv("COMPRESSION_MODEL", model),
        "final_report_model": os.getenv("FINAL_REPORT_MODEL", model),
        "openai_base_url": os.getenv(
            "OPENAI_BASE_URL", "http://[::1]:8000/v1"
        ),
    }


async def run_case(
    case: dict[str, Any], run_id: str, attempt: int
) -> dict[str, Any]:
    """Run one case through the compiled baseline graph."""
    from open_deep_research.deep_researcher import deep_researcher

    case_id = str(case["case_id"])
    thread_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{case_id}:{attempt}"))
    record_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"scholarmind:{run_id}:{case_id}:{attempt}")
    )
    configuration = runtime_configuration(thread_id)
    config = {"configurable": configuration}
    started_at = utc_now()
    start_time = time.perf_counter()
    metrics = EventMetrics()
    error: str | None = None
    tokens_before = read_vllm_token_counters()
    try:
        async for event in deep_researcher.astream_events(
            {"messages": [{"role": "user", "content": case["question"]}]},
            config,
            version="v2",
        ):
            metrics.consume(event)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    tokens_after = read_vllm_token_counters()
    if tokens_before is not None and tokens_after is not None:
        metrics.input_tokens = max(0, tokens_after[0] - tokens_before[0])
        metrics.output_tokens = max(0, tokens_after[1] - tokens_before[1])
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens
    duration_ms = round((time.perf_counter() - start_time) * 1000)
    completed_at = utc_now()
    final_report = str(metrics.final_state.get("final_report") or "")
    source_urls = extract_source_urls(final_report)
    if error:
        status = "failed"
    elif not final_report or final_report.startswith("Error generating final report"):
        status = "report_error"
        if not error and metrics.errors:
            error = "; ".join(metrics.errors)
    else:
        status = "success"
    safe_configuration = {
        key: value for key, value in configuration.items() if key != "thread_id"
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "run_id": run_id,
        "attempt": attempt,
        "case_id": case_id,
        "category": case.get("category", ""),
        "question": case["question"],
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "thread_id": thread_id,
        "graph_run_id": metrics.graph_run_id,
        "configuration": safe_configuration,
        "metrics": metrics.as_dict(duration_ms, len(source_urls)),
        "source_urls": source_urls,
        "final_report": final_report,
        "error": error,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Run ScholarMind baseline cases and append JSONL results."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--run-id",
        default="baseline-qwen3-local-v1",
        help="Stable experiment identifier used for safe resume.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Run only the selected stable case_id; may be repeated.",
    )
    parser.add_argument("--limit", type=int, help="Run at most this many selected cases.")
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Append another attempt even when this run already contains the case.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and list cases without importing the graph or calling a model.",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    """Execute selected cases sequentially and durably append results."""
    load_dotenv(ROOT / ".env")
    configure_local_no_proxy()
    cases = load_cases(args.cases)
    if args.case_ids:
        selected = set(args.case_ids)
        unknown = selected - {str(case["case_id"]) for case in cases}
        if unknown:
            raise ValueError(f"unknown case_id values: {sorted(unknown)}")
        cases = [case for case in cases if case["case_id"] in selected]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1")
        cases = cases[: args.limit]
    if args.dry_run:
        print(f"Validated {len(cases)} cases from {args.cases}")
        for case in cases:
            print(f"{case['case_id']}: {case['category']}")
        return 0
    records = load_existing_records(args.output)
    completed = completed_case_ids(records, args.run_id)
    runnable = (
        cases
        if args.rerun
        else [case for case in cases if case["case_id"] not in completed]
    )
    print(
        f"Run {args.run_id}: {len(runnable)} pending, "
        f"{len(cases) - len(runnable)} already recorded"
    )
    for index, case in enumerate(runnable, start=1):
        case_id = str(case["case_id"])
        attempt = next_attempt(records, args.run_id, case_id)
        print(f"[{index}/{len(runnable)}] {case_id} started")
        record = await run_case(case, args.run_id, attempt)
        append_record(args.output, record)
        records.append(record)
        print(
            f"[{index}/{len(runnable)}] {case_id} {record['status']} "
            f"{record['metrics']['duration_ms']}ms "
            f"{record['metrics']['tokens']['total']} tokens "
            f"{record['metrics']['sources_count']} sources"
        )
    print(f"Results appended to {args.output}")
    return 0


def main() -> int:
    """Run the CLI with concise validation failures."""
    args = parse_args()
    try:
        return asyncio.run(async_main(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
