"""Regression tests for the durable Baseline result contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "evaluation" / "schemas" / "baseline_result.schema.json"
RESULTS_DIRECTORY = ROOT / "evaluation" / "results"


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _historical_records() -> list[dict]:
    records: list[dict] = []
    for path in sorted(RESULTS_DIRECTORY.glob("*.jsonl")):
        records.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return records


def _partial_record() -> dict:
    record = copy.deepcopy(_historical_records()[0])
    research_error = {
        "stage": "researcher",
        "code": "researcher_execution_failed",
        "message": "one parallel research unit failed",
        "recoverable": True,
        "research_topic": "failed topic",
    }
    record.update(
        {
            "status": "partial",
            "research_status": "partial",
            "research_errors": [research_error],
            "evidence_count": 1,
            "error": "researcher_execution_failed: one unit failed",
        }
    )
    record["metrics"].update(
        {
            "research_status": "partial",
            "research_errors": [research_error],
            "evidence_count": 1,
            "degraded": True,
        }
    )
    return record


def test_schema_and_historical_results_remain_compatible() -> None:
    validator = _validator()
    records = _historical_records()

    assert records
    for record in records:
        validator.validate(record)


def test_structured_partial_result_is_valid() -> None:
    _validator().validate(_partial_record())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: record.update(status="degraded"),
        lambda record: record["research_errors"][0].pop("recoverable"),
        lambda record: record["research_errors"][0].update(secret="not allowed"),
    ],
)
def test_invalid_partial_contract_is_rejected(mutation) -> None:
    record = _partial_record()
    mutation(record)

    with pytest.raises(ValidationError):
        _validator().validate(record)
