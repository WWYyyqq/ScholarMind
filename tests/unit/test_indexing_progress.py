"""Durable JSONL indexing progress tests."""

import json
from pathlib import Path

from scholarmind.retrieval import (
    IndexingFailure,
    IndexingProgress,
    IndexingResult,
    JsonlIndexingProgressRecorder,
)


def test_progress_recorder_appends_start_batch_and_summary(tmp_path: Path) -> None:
    progress_path = tmp_path / "private" / "index.jsonl"
    recorder = JsonlIndexingProgressRecorder(
        progress_path,
        model="embedding-v1",
        total_count=2,
        resume=True,
    )
    failure = IndexingFailure(
        evidence_id="evidence-b",
        error_type="ValueError",
        message="invalid text",
    )
    recorder(
        IndexingProgress(
            status="failed",
            evidence_ids=("evidence-b",),
            total_count=2,
            completed_count=2,
            indexed_count=0,
            skipped_count=1,
            failed_count=1,
            failure=failure,
        )
    )
    result = IndexingResult(
        model="embedding-v1",
        total_count=2,
        indexed_count=0,
        evidence_ids=(),
        skipped_count=1,
        skipped_evidence_ids=("evidence-a",),
        failed_count=1,
        failures=(failure,),
        embedding_dimension=None,
    )
    recorder.finish(result, elapsed_seconds=1.2345)

    records = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == [
        "run_started",
        "batch_failed",
        "run_completed",
    ]
    assert len({record["run_id"] for record in records}) == 1
    assert records[1]["failure"]["evidence_id"] == "evidence-b"
    assert records[-1]["complete"] is False
    assert records[-1]["elapsed_seconds"] == 1.234
