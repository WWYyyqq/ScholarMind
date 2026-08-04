"""CLI tests that do not require PostgreSQL, a GPU, or model downloads."""

import hashlib
import json
from pathlib import Path

from scholarmind.cli import main


def _manifest_record() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "file_id": "file-0123456789abcdef",
        "paper_id": "paper-0123456789abcdef",
        "work_id": "work-0123456789abcdef",
        "relative_path": "papers/reliable.pdf",
        "canonical_relative_path": "papers/reliable.pdf",
        "filename": "reliable.pdf",
        "sha256": "a" * 64,
        "byte_size": 2048,
        "pages": 8,
        "title": "Reliable Retrieval",
        "language": "en",
        "document_type": "original",
        "year": 2026,
        "category": "information_retrieval",
        "study_type": "research",
        "index_policy": "primary",
        "indexable": True,
        "dataset_split": "development",
        "tuning_allowed": True,
        "is_exact_duplicate": False,
        "translation_of_paper_id": None,
        "semantic_duplicate_of_paper_id": None,
    }


def _chunk_record(index: int) -> dict[str, object]:
    text = f"Evidence passage {index} supports reliable retrieval."
    return {
        "schema_version": "1.0.0",
        "chunk_id": f"chunk-{index:016x}",
        "paper_id": "paper-0123456789abcdef",
        "work_id": "work-0123456789abcdef",
        "title": "Reliable Retrieval",
        "language": "en",
        "category": "information_retrieval",
        "indexable": True,
        "index_policy": "primary",
        "dataset_split": "development",
        "tuning_allowed": True,
        "page_number": index,
        "section": "Method",
        "text": text,
        "char_count": len(text),
        "token_estimate": 10,
        "bbox": [10, 20, 300, 400],
        "bbox_normalized_top_left": [0.01, 0.02, 0.5, 0.6],
        "block_ids": [f"p{index}-b1"],
        "block_orders": [0],
        "previous_chunk_id": None,
        "next_chunk_id": None,
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _write_dataset(directory: Path) -> None:
    (directory / "canonical_manifest.jsonl").write_text(
        json.dumps(_manifest_record()) + "\n",
        encoding="utf-8",
    )
    (directory / "chunks.development.jsonl").write_text(
        "\n".join(json.dumps(_chunk_record(index)) for index in (1, 2)) + "\n",
        encoding="utf-8",
    )
    (directory / "chunks.jsonl").write_text(
        json.dumps({"must": "never be read by the development CLI"}) + "\n",
        encoding="utf-8",
    )


def test_index_dry_run_reads_only_development_contract(
    tmp_path: Path,
    capsys,
) -> None:
    _write_dataset(tmp_path)

    exit_code = main(["index", "--dataset", str(tmp_path), "--dry-run"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset_split"] == "development"
    assert payload["source_count"] == 1
    assert payload["evidence_count"] == 2
    assert payload["dry_run"] is True


def test_index_limit_produces_small_service_free_smoke_bundle(
    tmp_path: Path,
    capsys,
) -> None:
    _write_dataset(tmp_path)

    exit_code = main(
        ["index", "--dataset", str(tmp_path), "--limit", "1", "--dry-run"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_count"] == 1
    assert payload["evidence_count"] == 1


def test_index_reports_missing_private_artifact(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(["index", "--dataset", str(tmp_path), "--dry-run"])

    assert exit_code == 2
    assert "chunks.development.jsonl" in capsys.readouterr().err
