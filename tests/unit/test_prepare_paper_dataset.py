"""Contract tests for the local paper-dataset preparation pipeline.

All PDFs in this module are generated from scratch with PyMuPDF.  The tests do
not inspect, copy, or otherwise access the user's real paper collection.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from collections import defaultdict
from pathlib import Path
from types import ModuleType

import pymupdf
import pytest

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "prepare_paper_dataset.py"


def _load_pipeline() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "prepare_paper_dataset_under_test", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - import guard
        raise RuntimeError(f"cannot import pipeline from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve annotations through sys.modules during decoration.
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pipeline = _load_pipeline()


def _make_text_pdf(
    path: Path,
    *,
    title: str,
    unique_text: str,
    two_columns: bool = False,
) -> None:
    """Create a small, searchable research-paper-like PDF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((48, 54), title, fontsize=18, fontname="hebo")
    page.insert_text((48, 76), "Synthetic Author, Example University", fontsize=12)
    abstract = (
        "Abstract. This synthetic paper studies reliable evidence-aware retrieval "
        "for complex software systems. It evaluates a deterministic method with "
        "traceable page locations and explicit document grouping. "
        f"Variant marker: {unique_text}. "
        "The material is intentionally long enough to exercise parsing and chunking."
    )
    page.insert_textbox((48, 95, 564, 215), abstract, fontsize=10.5)
    page.insert_text((48, 238), "1 Introduction", fontsize=14, fontname="hebo")
    if two_columns:
        left = (
            "The left column describes the problem, assumptions, dataset, and "
            "experimental protocol. Every statement is synthetic and exists only "
            "for this unit test. "
        ) * 4
        right = (
            "The right column explains the method, evidence links, bounding boxes, "
            "and reproducible evaluation. Every statement is synthetic and exists "
            "only for this unit test. "
        ) * 4
        page.insert_textbox((48, 260, 294, 705), left, fontsize=9.5)
        page.insert_textbox((318, 260, 564, 705), right, fontsize=9.5)
    else:
        body = (
            "This introduction provides sufficient extractable text for the OCR "
            "guard and gives the layout parser multiple sentences to process. "
            "The pipeline should retain source evidence without serializing an "
            "absolute source directory. "
        ) * 4
        page.insert_textbox((48, 260, 564, 650), body, fontsize=10.5)
    doc.set_metadata({"title": title})
    doc.save(path)
    doc.close()


def _make_blank_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(path)
    doc.close()


def _inspect_tree(source: Path) -> list[object]:
    pdfs = sorted(
        (path for path in source.rglob("*") if path.suffix.lower() == ".pdf"),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    return [pipeline.inspect_pdf(path, source) for path in pdfs]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _build_synthetic_corpus(source: Path) -> int:
    """Create exact duplicates, variants, a translation, and another work."""
    dated_original = source / "2026" / "Shared_Work.pdf"
    _make_text_pdf(
        dated_original,
        title="Shared Work: Evidence-aware Retrieval",
        unique_text="canonical-version-a",
    )
    # Byte-for-byte duplicate: same paper_id, one logical canonical file.
    baseline_duplicate = source / "baseline" / "Shared_Work.pdf"
    baseline_duplicate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dated_original, baseline_duplicate)

    # Same logical work, different bytes/content: only one English version is primary.
    _make_text_pdf(
        source / "revised" / "Shared_Work.pdf",
        title="Shared Work: Evidence-aware Retrieval (revised layout)",
        unique_text="non-identical-version-b",
        two_columns=True,
    )
    # Translation is not an exact duplicate but shares normalized title/work_id.
    _make_text_pdf(
        source / "translations" / "Shared_Work_翻译结果.pdf",
        title="Shared Work Chinese Translation",
        unique_text="translation-content-is-distinct",
    )
    _make_text_pdf(
        source / "other" / "Independent_Work.PDF",
        title="Independent Work on Observability",
        unique_text="independent-work",
    )

    # Non-PDF files must be ignored completely.
    (source / "notes.txt").write_text("not a paper", encoding="utf-8")
    (source / "labels.xlsx").write_bytes(b"not a real workbook")
    (source / "draft.docx").write_bytes(b"not a real document")
    return 5


def test_manifest_exact_dedup_translation_and_single_primary(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _build_synthetic_corpus(source)

    manifest = pipeline.build_manifest(_inspect_tree(source))
    assert all("Synthetic Author" not in str(record["title"]) for record in manifest)
    shared = [
        record for record in manifest if record["normalized_title"] == "sharedwork"
    ]
    assert len(shared) == 4

    # Locate by digest instead of relying on traversal/canonical ordering.
    by_digest: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in shared:
        by_digest[str(record["sha256"])].append(record)
    duplicate_groups = [group for group in by_digest.values() if len(group) == 2]
    assert len(duplicate_groups) == 1
    exact_group = duplicate_groups[0]
    assert sum(not record["is_exact_duplicate"] for record in exact_group) == 1
    assert len({record["paper_id"] for record in exact_group}) == 1
    duplicate = next(record for record in exact_group if record["is_exact_duplicate"])
    canonical = next(
        record for record in exact_group if not record["is_exact_duplicate"]
    )
    assert duplicate["duplicate_of_file_id"] == canonical["file_id"]
    assert canonical["relative_path"] == "2026/Shared_Work.pdf"

    nonduplicates = [record for record in shared if not record["is_exact_duplicate"]]
    originals = [
        record for record in nonduplicates if record["document_type"] == "original"
    ]
    translations = [
        record for record in nonduplicates if record["document_type"] == "translation"
    ]
    assert len(originals) == 2
    assert len(translations) == 1
    assert len({record["sha256"] for record in nonduplicates}) == 3
    assert len({record["work_id"] for record in shared}) == 1
    assert translations[0]["translation_of_paper_id"] in {
        record["paper_id"] for record in originals
    }

    # Work-level policy is separate from byte-level de-duplication.
    assert sum(record.get("index_policy") == "primary" for record in originals) == 1
    assert (
        sum(
            record.get("index_policy") == "skip_semantic_variant"
            for record in originals
        )
        == 1
    )
    assert translations[0].get("index_policy") == "auxiliary_translation"
    assert duplicate.get("index_policy") == "skip_exact_duplicate"


def test_split_text_rejects_non_positive_limit() -> None:
    for invalid in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            pipeline.split_text_for_chunks("text", invalid)


def test_oversized_block_is_split_at_strict_character_limit() -> None:
    text = ("Alpha beta gamma. " * 200).strip()

    parts = pipeline.split_text_for_chunks(text, max_chars=500)

    assert len(parts) > 1
    assert all(0 < len(part) <= 500 for part in parts)
    assert " ".join(parts) == text


def test_output_directory_must_be_outside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _build_synthetic_corpus(source)

    with pytest.raises(ValueError, match="outside source"):
        pipeline.build_dataset(
            source_root=source,
            output=source / "generated",
            eval_size=1,
            max_chunk_chars=500,
            replace=False,
        )

    with pytest.raises(ValueError, match="outside source"):
        pipeline.build_dataset(
            source_root=source,
            output=tmp_path,
            eval_size=1,
            max_chunk_chars=500,
            replace=True,
        )


def test_end_to_end_scans_only_pdf_uses_relative_paths_and_prevents_split_leakage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-with-private-name"
    expected_pdf_count = _build_synthetic_corpus(source)
    output = tmp_path / "dataset"

    summary = pipeline.build_dataset(
        source_root=source,
        output=output,
        eval_size=1,
        max_chunk_chars=500,
        replace=False,
    )

    assert summary["source_pdf_count"] == expected_pdf_count
    assert summary["valid_pdf_count"] == expected_pdf_count
    manifest = _read_jsonl(output / "manifest.jsonl")
    assert len(manifest) == expected_pdf_count
    assert all(str(record["filename"]).lower().endswith(".pdf") for record in manifest)
    assert not any(
        str(record["filename"]).lower().endswith((".docx", ".xlsx", ".txt"))
        for record in manifest
    )

    source_absolute = str(source.resolve())
    serialized_files = [
        output / "manifest.jsonl",
        output / "canonical_manifest.jsonl",
        output / "chunks.jsonl",
        output / "chunks.development.jsonl",
        output / "evaluation" / "corpus.chunks.jsonl",
        output / "evaluation" / "questions.silver.jsonl",
        output / "dataset_config.json",
    ] + sorted((output / "documents").glob("*.json"))
    assert all(
        source_absolute not in path.read_text(encoding="utf-8")
        for path in serialized_files
    )
    assert all(
        not Path(str(record["relative_path"])).is_absolute() for record in manifest
    )
    config = json.loads((output / "dataset_config.json").read_text(encoding="utf-8"))
    assert config["source_root"] == "provided-at-runtime-and-not-serialized"
    assert config["pdf_only"] is True
    assert config["source_files_copied"] is False

    splits_by_work: dict[str, set[str]] = defaultdict(set)
    tuning_by_work: dict[str, set[bool]] = defaultdict(set)
    for record in manifest:
        splits_by_work[str(record["work_id"])].add(str(record["dataset_split"]))
        tuning_by_work[str(record["work_id"])].add(bool(record["tuning_allowed"]))
    assert all(len(splits) == 1 for splits in splits_by_work.values())
    assert all(len(values) == 1 for values in tuning_by_work.values())

    held_out = {
        work_id for work_id, splits in splits_by_work.items() if splits == {"test"}
    }
    eval_papers = _read_jsonl(output / "evaluation" / "papers.jsonl")
    assert held_out == {str(record["work_id"]) for record in eval_papers}
    assert all(record["tuning_allowed"] is False for record in eval_papers)
    all_chunks = _read_jsonl(output / "chunks.jsonl")
    development_chunks = _read_jsonl(output / "chunks.development.jsonl")
    evaluation_chunks = _read_jsonl(output / "evaluation" / "corpus.chunks.jsonl")
    development_ids = {str(chunk["chunk_id"]) for chunk in development_chunks}
    evaluation_ids = {str(chunk["chunk_id"]) for chunk in evaluation_chunks}
    assert development_ids.isdisjoint(evaluation_ids)
    assert development_ids == {
        str(chunk["chunk_id"])
        for chunk in all_chunks
        if chunk["dataset_split"] == "development" and chunk["indexable"]
    }
    assert evaluation_ids == {
        str(chunk["chunk_id"])
        for chunk in all_chunks
        if chunk["dataset_split"] == "test" and chunk["indexable"]
    }
    assert all(chunk["tuning_allowed"] is True for chunk in development_chunks)
    assert all(chunk["tuning_allowed"] is False for chunk in evaluation_chunks)
    assert summary["development_chunk_count"] == len(development_chunks)
    assert summary["evaluation_corpus_chunk_count"] == len(evaluation_chunks)


def test_page_bbox_and_chunk_traceability(tmp_path: Path) -> None:
    source = tmp_path / "source"
    pdf = source / "Traceable_Work.pdf"
    _make_text_pdf(
        pdf,
        title="Traceable Work with Two Columns",
        unique_text="traceable-layout",
        two_columns=True,
    )
    record = pipeline.build_manifest([pipeline.inspect_pdf(pdf, source)])[0]

    document, chunks = pipeline.parse_document(
        pdf,
        record,
        aliases=["Traceable_Work.pdf"],
        max_chars=500,
    )

    assert document["coordinate_space"] == "pdf_points_top_left"
    assert document["pages_count"] == 1
    assert document["chunk_count"] == len(chunks)
    assert chunks
    page = document["pages"][0]
    block_orders = {block["reading_order"] for block in page["text_blocks"]}
    assert {block["column"] for block in page["text_blocks"]} >= {"left", "right"}
    for chunk in chunks:
        assert chunk["paper_id"] == document["paper_id"]
        assert chunk["work_id"] == document["work_id"]
        assert chunk["page_number"] == page["page_number"] == 1
        assert set(chunk["block_orders"]) <= block_orders
        x0, y0, x1, y1 = chunk["bbox"]
        assert 0 <= x0 <= x1 <= page["width"]
        assert 0 <= y0 <= y1 <= page["height"]
        normalized = pipeline.normalized_bbox(document, 1, chunk["bbox"])
        assert all(0.0 <= value <= 1.0 for value in normalized)
        assert len(chunk["content_sha256"]) == 64
        assert chunk["char_count"] == len(chunk["text"])
        assert chunk["char_count"] <= 500
    for index, chunk in enumerate(chunks):
        expected_previous = chunks[index - 1]["chunk_id"] if index else None
        expected_next = (
            chunks[index + 1]["chunk_id"] if index + 1 < len(chunks) else None
        )
        assert chunk["previous_chunk_id"] == expected_previous
        assert chunk["next_chunk_id"] == expected_next


def test_textless_scanned_pdf_is_reported_as_needing_ocr(tmp_path: Path) -> None:
    source = tmp_path / "source"
    pdf = source / "Scanned_Work.pdf"
    _make_blank_pdf(pdf)
    record = pipeline.build_manifest([pipeline.inspect_pdf(pdf, source)])[0]

    with pytest.raises(ValueError, match=r"needs OCR|too little extractable text"):
        pipeline.parse_document(
            pdf,
            record,
            aliases=["Scanned_Work.pdf"],
            max_chars=500,
        )
