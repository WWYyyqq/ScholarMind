"""Compatibility tests for baseline and PR5 paper-dataset records."""

import hashlib
import json
from pathlib import Path

import pytest

from scholarmind.adapters import BaselineEvidenceAdapter, PaperDatasetAdapter
from scholarmind.adapters.paper_dataset import PaperDatasetRecordError


def _manifest_record(**updates):
    record = {
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
    record.update(updates)
    return record


def _chunk_record(**updates):
    record = {
        "schema_version": "1.0.0",
        "chunk_id": "chunk-0123456789abcdef",
        "paper_id": "paper-0123456789abcdef",
        "work_id": "work-0123456789abcdef",
        "title": "Reliable Retrieval",
        "language": "en",
        "category": "information_retrieval",
        "indexable": True,
        "index_policy": "primary",
        "dataset_split": "development",
        "tuning_allowed": True,
        "page_number": 4,
        "section": "3 Method",
        "text": "The method combines dense retrieval with BM25 using RRF.",
        "char_count": 61,
        "token_estimate": 14,
        "bbox": [10, 20, 300, 400],
        "bbox_normalized_top_left": [0.01, 0.02, 0.5, 0.6],
        "block_ids": ["p4-b1", "p4-b2"],
        "block_orders": [0, 1],
        "previous_chunk_id": None,
        "next_chunk_id": None,
    }
    record.update(updates)
    if "content_sha256" not in updates:
        record["content_sha256"] = hashlib.sha256(
            str(record["text"]).encode("utf-8")
        ).hexdigest()
    return record


def test_pr5_records_preserve_page_chunk_and_block_location() -> None:
    bundle = PaperDatasetAdapter.from_records(
        [_manifest_record()], [_chunk_record()]
    )

    assert len(bundle.sources) == 1
    assert len(bundle.evidence) == 1
    source = bundle.sources[0]
    evidence = bundle.evidence[0]
    assert source.paper_id == "paper-0123456789abcdef"
    assert source.work_id == "work-0123456789abcdef"
    assert source.uri == "papers/reliable.pdf"
    assert evidence.source_id == source.source_id
    assert evidence.locator.page_number == 4
    assert evidence.locator.chunk_id == "chunk-0123456789abcdef"
    assert evidence.locator.block_ids == ("p4-b1", "p4-b2")
    assert evidence.locator.bbox == (10.0, 20.0, 300.0, 400.0)


def test_exact_duplicate_manifest_rows_create_one_source() -> None:
    duplicate = _manifest_record(
        file_id="file-fedcba9876543210",
        relative_path="baseline/reliable.pdf",
        is_exact_duplicate=True,
        indexable=False,
    )
    bundle = PaperDatasetAdapter.from_records(
        [duplicate, _manifest_record()], [_chunk_record()]
    )

    assert len(bundle.sources) == 1
    assert bundle.sources[0].uri == "papers/reliable.pdf"


def test_jsonl_loader_consumes_pipeline_outputs(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path.write_text(json.dumps(_manifest_record()) + "\n", encoding="utf-8")
    chunks_path.write_text(json.dumps(_chunk_record()) + "\n", encoding="utf-8")

    bundle = PaperDatasetAdapter.load_jsonl(manifest_path, chunks_path)

    assert len(bundle.sources) == len(bundle.evidence) == 1


def test_default_bundle_excludes_test_split_even_when_given_all_records() -> None:
    test_manifest = _manifest_record(
        file_id="file-fedcba9876543210",
        paper_id="paper-fedcba9876543210",
        work_id="work-fedcba9876543210",
        relative_path="test/held-out.pdf",
        canonical_relative_path="test/held-out.pdf",
        filename="held-out.pdf",
        sha256="c" * 64,
        dataset_split="test",
        tuning_allowed=False,
    )
    test_chunk = _chunk_record(
        chunk_id="chunk-fedcba9876543210",
        paper_id="paper-fedcba9876543210",
        work_id="work-fedcba9876543210",
        text="Held-out evidence must never leak into development retrieval.",
        dataset_split="test",
        tuning_allowed=False,
    )
    manifests = [_manifest_record(), test_manifest]
    chunks = [_chunk_record(), test_chunk]

    development = PaperDatasetAdapter.from_records(manifests, chunks)
    held_out = PaperDatasetAdapter.from_records(
        manifests, chunks, dataset_split="test"
    )

    assert development.dataset_split == "development"
    assert held_out.dataset_split == "test"
    assert {item.paper_id for item in development.sources} == {
        "paper-0123456789abcdef"
    }
    assert {item.paper_id for item in held_out.sources} == {
        "paper-fedcba9876543210"
    }
    assert {item.evidence_id for item in development.evidence}.isdisjoint(
        item.evidence_id for item in held_out.evidence
    )


def test_unknown_chunk_paper_is_rejected() -> None:
    with pytest.raises(PaperDatasetRecordError, match="unknown paper_id"):
        PaperDatasetAdapter.from_records(
            [_manifest_record()],
            [_chunk_record(paper_id="paper-fedcba9876543210")],
        )


def test_baseline_adapter_does_not_treat_generated_report_as_evidence() -> None:
    record = {
        "run_id": "day4",
        "record_id": "record-1",
        "source_urls": ["https://example.org/paper", "https://example.org/paper"],
        "final_report": "A model-generated assertion is not raw source evidence.",
    }

    sources = BaselineEvidenceAdapter.sources_from_run(record)

    assert len(sources) == 1
    assert sources[0].uri == "https://example.org/paper"


def test_baseline_raw_result_can_become_located_evidence() -> None:
    source, evidence = BaselineEvidenceAdapter.from_search_result(
        {
            "url": "https://example.org/source",
            "title": "Primary source",
            "content": "The measured latency was 12 milliseconds.",
        },
        query="measured latency",
    )

    assert evidence.source_id == source.source_id
    assert evidence.locator.section == "web-search-result"
