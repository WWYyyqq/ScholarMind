"""Synthetic contract tests for the paper-dataset validator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from test_prepare_paper_dataset import _build_synthetic_corpus, pipeline  # noqa: E402
from validate_paper_dataset import validate_dataset  # noqa: E402

SCHEMAS = Path(__file__).parents[2] / "evaluation" / "schemas"


def test_validator_accepts_synthetic_pipeline_output(tmp_path: Path) -> None:
    """Validate a generated corpus without touching the user's real PDFs."""
    source = tmp_path / "source"
    _build_synthetic_corpus(source)
    dataset = tmp_path / "dataset"
    pipeline.build_dataset(
        source_root=source,
        output=dataset,
        eval_size=1,
        max_chunk_chars=500,
        replace=False,
    )

    report = validate_dataset(dataset, SCHEMAS)

    assert report["valid"] is True, report["errors"]
    assert report["error_count"] == 0
    assert report["counts"]["manifest"] == 5
    assert report["counts"]["schemas"] == 4


def test_validator_rejects_failed_source_integrity_flag(tmp_path: Path) -> None:
    """Reject a dataset whose source-integrity attestation is not true."""
    source = tmp_path / "source"
    _build_synthetic_corpus(source)
    dataset = tmp_path / "dataset"
    pipeline.build_dataset(
        source_root=source,
        output=dataset,
        eval_size=1,
        max_chunk_chars=500,
        replace=False,
    )
    config_path = dataset / "dataset_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["source_integrity_verified"] = False
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report = validate_dataset(dataset, SCHEMAS)

    assert report["valid"] is False
    assert "dataset_config.source_integrity_verified is not true" in report["errors"]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def test_validator_rejects_chunk_length_and_hash_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _build_synthetic_corpus(source)
    dataset = tmp_path / "dataset"
    pipeline.build_dataset(source, dataset, 1, 500, False)
    chunks_path = dataset / "chunks.jsonl"
    chunks = [
        json.loads(line)
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
    ]
    chunks[0]["char_count"] = int(chunks[0]["char_count"]) + 1
    chunks[1]["content_sha256"] = "0" * 64
    _write_jsonl(chunks_path, chunks)

    report = validate_dataset(dataset, SCHEMAS)

    assert report["valid"] is False
    assert any("char_count does not match" in error for error in report["errors"])
    assert any("content_sha256 does not match" in error for error in report["errors"])


def test_validator_rejects_partition_and_evidence_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _build_synthetic_corpus(source)
    dataset = tmp_path / "dataset"
    pipeline.build_dataset(source, dataset, 1, 500, False)
    development_path = dataset / "chunks.development.jsonl"
    development = [
        json.loads(line)
        for line in development_path.read_text(encoding="utf-8").splitlines()
    ]
    _write_jsonl(development_path, development[1:])
    questions_path = dataset / "evaluation" / "questions.silver.jsonl"
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
    ]
    assert questions
    questions[0]["answer"] = "fabricated answer"
    questions[0]["evidence"]["text"] = "fabricated answer"
    questions[0]["evidence"]["bbox_normalized_top_left"] = [0.0, 0.0, 0.0, 0.0]
    _write_jsonl(questions_path, questions)

    report = validate_dataset(dataset, SCHEMAS)

    assert report["valid"] is False
    assert any(
        "exact development/indexable partition" in error for error in report["errors"]
    )
    assert any(
        "not extractive from referenced blocks" in error for error in report["errors"]
    )
    assert any("normalized bbox does not match" in error for error in report["errors"])


def test_validator_rejects_tampered_duplicate_relationship(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _build_synthetic_corpus(source)
    dataset = tmp_path / "dataset"
    pipeline.build_dataset(source, dataset, 1, 500, False)
    manifest_path = dataset / "manifest.jsonl"
    manifest = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
    ]
    duplicate = next(record for record in manifest if record["is_exact_duplicate"])
    duplicate["duplicate_of_file_id"] = duplicate["file_id"]
    duplicate["canonical_relative_path"] = "tampered.pdf"
    _write_jsonl(manifest_path, manifest)

    report = validate_dataset(dataset, SCHEMAS)

    assert report["valid"] is False
    assert any(
        "canonical_relative_path mismatch" in error for error in report["errors"]
    )
    assert any(
        "invalid exact-duplicate relationship" in error for error in report["errors"]
    )
