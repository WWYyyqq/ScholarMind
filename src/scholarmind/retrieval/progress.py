"""Append-only progress logs for resumable local indexing runs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .indexing import IndexingProgress, IndexingResult


class JsonlIndexingProgressRecorder:
    """Persist run and batch events without storing paper text or credentials."""

    def __init__(
        self,
        path: Path,
        *,
        model: str,
        total_count: int,
        resume: bool,
    ) -> None:
        """Create a run ID and append a durable start record."""
        self.path = path.expanduser().resolve()
        self.run_id = uuid4().hex
        self.model = model
        self.total_count = total_count
        self.resume = resume
        self._append(
            {
                "event": "run_started",
                "model": model,
                "total_count": total_count,
                "resume": resume,
            }
        )

    def __call__(self, progress: IndexingProgress) -> None:
        """Append one terminal batch progress event."""
        failure = (
            asdict(progress.failure) if progress.failure is not None else None
        )
        self._append(
            {
                "event": "batch_" + progress.status,
                "evidence_ids": list(progress.evidence_ids),
                "total_count": progress.total_count,
                "completed_count": progress.completed_count,
                "indexed_count": progress.indexed_count,
                "skipped_count": progress.skipped_count,
                "failed_count": progress.failed_count,
                "failure": failure,
            }
        )

    def finish(self, result: IndexingResult, *, elapsed_seconds: float) -> None:
        """Append the final run summary."""
        self._append(
            {
                "event": "run_completed",
                "complete": result.complete,
                "model": result.model,
                "total_count": result.total_count,
                "indexed_count": result.indexed_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
                "embedding_dimension": result.embedding_dimension,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "failures": [asdict(item) for item in result.failures],
            }
        )

    def fail(self, error: Exception, *, elapsed_seconds: float) -> None:
        """Record a systemic interruption that should be fixed before resuming."""
        self._append(
            {
                "event": "run_interrupted",
                "model": self.model,
                "total_count": self.total_count,
                "error_type": type(error).__name__,
                "message": " ".join(str(error).split()) or repr(error),
                "elapsed_seconds": round(elapsed_seconds, 3),
            }
        )

    def _append(self, payload: dict[str, Any]) -> None:
        """Append and fsync one compact JSON event."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": "1.0.0",
            "run_id": self.run_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
