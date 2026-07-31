import json
from pathlib import Path

from scripts.run_baseline import (
    append_record,
    completed_case_ids,
    configure_local_no_proxy,
    extract_source_urls,
    load_cases,
    load_existing_records,
    next_attempt,
)


def test_fixed_cases_have_unique_stable_ids():
    cases = load_cases(Path("evaluation/cases/baseline.jsonl"))

    assert 8 <= len(cases) <= 10
    assert [case["case_id"] for case in cases] == [
        f"baseline-{index:03d}" for index in range(1, len(cases) + 1)
    ]


def test_extract_source_urls_preserves_order_and_deduplicates():
    report = (
        "A https://example.com/a. B (https://example.com/b), "
        "again https://example.com/a."
    )

    assert extract_source_urls(report) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_append_only_results_support_resume_and_attempts(tmp_path):
    output = tmp_path / "results.jsonl"
    first = {"run_id": "run-1", "case_id": "baseline-001", "attempt": 1}
    second = {"run_id": "run-2", "case_id": "baseline-001", "attempt": 1}

    append_record(output, first)
    append_record(output, second)
    records = load_existing_records(output)

    assert records == [first, second]
    assert completed_case_ids(records, "run-1") == {"baseline-001"}
    assert completed_case_ids(records, "run-2") == {"baseline-001"}
    assert next_attempt(records, "run-1", "baseline-001") == 2
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2
    assert all(json.loads(line) for line in output.read_text().splitlines())


def test_local_model_bypasses_inherited_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.delenv("no_proxy", raising=False)

    configure_local_no_proxy()

    assert set(__import__("os").environ["NO_PROXY"].split(",")) >= {
        "example.com", "127.0.0.1", "localhost", "::1"
    }
    assert __import__("os").environ["no_proxy"] == "127.0.0.1,localhost,::1"
