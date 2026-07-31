#!/usr/bin/env python3
"""Compute reproducible Day 4 metrics from baseline results and labels."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "evaluation/results/day3-qwen3-local-20260731.jsonl"
DEFAULT_LABELS = ROOT / "evaluation/labels/baseline.csv"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load append-only JSONL records."""
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def latest_by_case(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Select the highest attempt for every stable case ID."""
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = str(record["case_id"])
        if case_id not in latest or int(record.get("attempt", 1)) >= int(
            latest[case_id].get("attempt", 1)
        ):
            latest[case_id] = record
    return latest


def load_labels(path: Path) -> list[dict[str, str]]:
    """Load manual claim and citation labels."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def percentage(numerator: int, denominator: int) -> float:
    """Return a rounded percentage with a zero-safe denominator."""
    return round(100 * numerator / denominator, 2) if denominator else 0.0


def summarize(
    records: list[dict[str, Any]], labels: list[dict[str, str]]
) -> dict[str, Any]:
    """Summarize latest case runs and manual labels."""
    latest = latest_by_case(records)
    current = [latest[key] for key in sorted(latest)]
    cited = [row for row in labels if row["citation_present"] == "true"]
    temporal = [row for row in labels if row["temporal_correct"] in {"true", "false"}]
    numeric = [row for row in labels if row["numeric_correct"] in {"true", "false"}]
    errors: Counter[str] = Counter()
    for row in labels:
        for error_type in row["error_types"].split("|"):
            if error_type:
                errors[error_type] += 1
    durations = [row["metrics"]["duration_ms"] for row in current]
    tokens = [row["metrics"]["tokens"]["total"] for row in current]
    sources = [row["metrics"]["sources_count"] for row in current]
    return {
        "result_file_records": len(records),
        "latest_case_count": len(current),
        "latest_status_counts": dict(
            sorted(Counter(row["status"] for row in current).items())
        ),
        "degraded_case_count": sum(
            bool(row["metrics"].get("degraded")) for row in current
        ),
        "average_duration_ms": round(mean(durations)) if durations else 0,
        "average_total_tokens": round(mean(tokens)) if tokens else 0,
        "average_sources": round(mean(sources), 2) if sources else 0.0,
        "total_executed_searches": sum(
            row["metrics"]["tool_calls"]["search"] for row in current
        ),
        "total_requested_searches": sum(
            row["metrics"]["tool_calls"].get("requested_search", 0)
            for row in current
        ),
        "claim_count": len(labels),
        "citation_precision_percent": percentage(
            sum(row["citation_support"] == "supported" for row in cited),
            len(cited),
        ),
        "citation_coverage_percent": percentage(len(cited), len(labels)),
        "citation_source_validity_percent": percentage(
            sum(row["source_exists"] == "true" for row in cited), len(cited)
        ),
        "factual_accuracy_percent": percentage(
            sum(row["factual_correct"] == "true" for row in labels), len(labels)
        ),
        "temporal_accuracy_percent": percentage(
            sum(row["temporal_correct"] == "true" for row in temporal),
            len(temporal),
        ),
        "numeric_accuracy_percent": percentage(
            sum(row["numeric_correct"] == "true" for row in numeric), len(numeric)
        ),
        "scope_completeness_percent": percentage(
            sum(row["scope_complete"] == "true" for row in labels), len(labels)
        ),
        "error_type_counts": dict(sorted(errors.items())),
        "metric_definitions": {
            "citation_precision": "supported cited claims / claims with a citation",
            "citation_coverage": "claims with a citation / all labeled factual claims",
            "source_validity": "cited claims whose exact source target exists / cited claims",
            "factual_accuracy": "factually correct claims / all labeled claims",
        },
    }


def parse_args() -> argparse.Namespace:
    """Parse analysis CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    """Compute, print, and optionally save the summary JSON."""
    args = parse_args()
    summary = summarize(load_jsonl(args.results), load_labels(args.labels))
    payload = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    print(payload, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
