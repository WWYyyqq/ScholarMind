"""Tests for the private Silver retrieval evaluation helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "evaluate_paper_retrieval.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "evaluate_paper_retrieval",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluation = _load_module()


def test_load_silver_questions_reads_required_fields(tmp_path: Path) -> None:
    questions_path = tmp_path / "questions.silver.jsonl"
    record = {
        "question_id": "q-001",
        "question": "What changed?",
        "paper_id": "paper-001",
        "evidence": {
            "page_number": 3,
            "text": "A substantive labeled passage.",
        },
    }
    questions_path.write_text(
        json.dumps(record) + "\n",
        encoding="utf-8",
    )

    questions = evaluation.load_silver_questions(questions_path)

    assert len(questions) == 1
    assert questions[0].question_id == "q-001"
    assert questions[0].paper_id == "paper-001"
    assert questions[0].page_number == 3


def test_load_silver_questions_rejects_duplicate_ids(tmp_path: Path) -> None:
    questions_path = tmp_path / "questions.silver.jsonl"
    record = {
        "question_id": "q-001",
        "question": "What changed?",
        "paper_id": "paper-001",
        "evidence": {
            "page_number": 3,
            "text": "A substantive labeled passage.",
        },
    }
    questions_path.write_text(
        json.dumps(record) + "\n" + json.dumps(record) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate question_id"):
        evaluation.load_silver_questions(questions_path)


def test_summarize_computes_recall_mrr_noise_and_latency() -> None:
    cases = [
        evaluation.CaseResult("q-1", 1, 2, 4, 8, 0, 0.2),
        evaluation.CaseResult("q-2", None, None, None, 4, 1, 0.4),
    ]

    summary = evaluation._summarize(cases)

    assert summary == {
        "case_count": 2,
        "source_recall_at_k": 0.5,
        "page_recall_at_k": 0.5,
        "exact_recall_at_k": 0.5,
        "source_mrr": 0.5,
        "page_mrr": 0.25,
        "exact_mrr": 0.125,
        "rejected_result_rate": 0.083333,
        "mean_latency_seconds": 0.3,
    }
