#!/usr/bin/env python3
"""Evaluate deterministic or Qwen semantic claim verification on safe fixtures."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scholarmind.models import Claim, Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.verification import (
    ClaimVerifier,
    OpenAISemanticEntailmentProvider,
    SemanticClaimVerifier,
)

DEFAULT_CASES = Path("evaluation/claim-verifier/cases.synthetic.jsonl")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a content-safe claim-verifier classification evaluation."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--mode",
        choices=("deterministic", "semantic"),
        default="deterministic",
    )
    parser.add_argument("--model", default="qwen3-14b-local")
    parser.add_argument("--base-url", default="http://[::1]:8000/v1")
    parser.add_argument("--api-key", default="local-not-required")
    parser.add_argument("--minimum-confidence", type=float, default=0.75)
    parser.add_argument("--output", type=Path)
    return parser


def _load_cases(path: Path) -> tuple[dict[str, Any], ...]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            required = {"case_id", "claim", "evidence", "expected"}
            if set(raw) != required:
                raise ValueError(f"line {line_number} has an invalid case contract")
            case_id = raw["case_id"]
            if not isinstance(case_id, str) or not case_id or case_id in seen:
                raise ValueError(f"line {line_number} has an invalid case_id")
            evidence = raw["evidence"]
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"line {line_number} requires evidence text")
            if raw["expected"] not in {
                "supported",
                "partial",
                "contradicted",
                "insufficient",
            }:
                raise ValueError(f"line {line_number} has an invalid expected label")
            seen.add(case_id)
            cases.append(raw)
    if not cases:
        raise ValueError("evaluation case file is empty")
    return tuple(cases)


def _models(case: dict[str, Any]) -> tuple[Claim, tuple[Evidence, ...]]:
    source = Source.create(
        kind=SourceKind.PAPER,
        title=f"Synthetic verifier fixture {case['case_id']}",
        uri=f"file:///synthetic/{case['case_id']}.pdf",
    )
    evidence = tuple(
        Evidence.create(
            source_id=source.source_id,
            text=text,
            locator=EvidenceLocator(
                page_number=index,
                chunk_id=f"{case['case_id']}-{index}",
            ),
        )
        for index, text in enumerate(case["evidence"], start=1)
    )
    claim = Claim.create(
        text=case["claim"],
        evidence_ids=tuple(item.evidence_id for item in evidence),
    )
    return claim, evidence


def _summary(
    records: list[dict[str, Any]],
    *,
    mode: str,
    model: str | None,
) -> dict[str, Any]:
    correct = sum(item["correct"] for item in records)
    expected_publish = sum(item["expected"] == "supported" for item in records)
    predicted_publish = sum(item["predicted"] == "supported" for item in records)
    true_publish = sum(
        item["expected"] == item["predicted"] == "supported"
        for item in records
    )
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for item in records:
        confusion[item["expected"]][item["predicted"]] += 1
    return {
        "mode": mode,
        "model": model,
        "case_count": len(records),
        "correct_count": correct,
        "accuracy": round(correct / len(records), 4),
        "publication_precision": round(
            true_publish / predicted_publish if predicted_publish else 0.0,
            4,
        ),
        "publication_recall": round(
            true_publish / expected_publish if expected_publish else 0.0,
            4,
        ),
        "confusion": {
            expected: dict(sorted(predicted.items()))
            for expected, predicted in sorted(confusion.items())
        },
        "cases": records,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the selected verifier and print only IDs, verdicts, and metrics."""
    args = _parser().parse_args(argv)
    cases = _load_cases(args.cases)
    provider = None
    if args.mode == "semantic":
        provider = OpenAISemanticEntailmentProvider(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
        )
        verifier = SemanticClaimVerifier(
            provider,
            minimum_confidence=args.minimum_confidence,
        )
    else:
        verifier = ClaimVerifier()

    records: list[dict[str, Any]] = []
    try:
        for case in cases:
            claim, evidence = _models(case)
            result = verifier.verify(claim, evidence)
            records.append(
                {
                    "case_id": case["case_id"],
                    "expected": case["expected"],
                    "predicted": result.status.value,
                    "correct": result.status.value == case["expected"],
                    "confidence": round(result.confidence, 4),
                    "method": result.verification_method,
                    "hard_gate_passed": result.hard_gate_passed,
                }
            )
    finally:
        if provider is not None:
            provider.close()

    payload = _summary(
        records,
        mode=args.mode,
        model=args.model if args.mode == "semantic" else None,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
