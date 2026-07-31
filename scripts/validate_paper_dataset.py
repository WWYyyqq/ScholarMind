#!/usr/bin/env python3
"""Validate a generated ScholarMind paper dataset and its cross-file invariants."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "manifest": "paper_manifest.schema.json",
    "document": "parsed_document.schema.json",
    "chunk": "paper_chunk.schema.json",
    "question": "paper_eval_question.schema.json",
}
MAX_REPORTED_ERRORS = 50
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


class ValidationReport:
    """Collect validation errors without aborting after the first failure."""

    def __init__(self) -> None:
        """Initialize an empty validation report."""
        self.errors: list[str] = []

    def add(self, message: str) -> None:
        """Record one unique error message."""
        if message not in self.errors:
            self.errors.append(message)

    def require(self, condition: bool, message: str) -> None:
        """Record ``message`` when ``condition`` is false."""
        if not condition:
            self.add(message)


def read_json(path: Path, report: ValidationReport) -> Any:
    """Read one JSON file, recording a useful error on failure."""
    if not path.is_file():
        report.add(f"missing file: {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.add(f"invalid JSON in {path.name}: {type(exc).__name__}: {exc}")
        return None


def read_jsonl(path: Path, report: ValidationReport) -> list[dict[str, Any]]:
    """Read a JSON Lines file and retain every valid object record."""
    if not path.is_file():
        report.add(f"missing file: {path.name}")
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        report.add(f"cannot read {path.name}: {type(exc).__name__}: {exc}")
        return []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            report.add(f"{path.name}:{line_number}: blank JSONL line")
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            report.add(f"{path.name}:{line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(payload, dict):
            report.add(f"{path.name}:{line_number}: record must be an object")
            continue
        records.append(payload)
    return records


def format_json_path(parts: Iterable[Any]) -> str:
    """Format a jsonschema path compactly for diagnostics."""
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def validate_records(
    records: Iterable[dict[str, Any]],
    validator: Draft202012Validator,
    label: str,
    report: ValidationReport,
) -> int:
    """Validate records against one JSON Schema and return their count."""
    count = 0
    for count, record in enumerate(records, start=1):
        for error in sorted(
            validator.iter_errors(record),
            key=lambda item: tuple(str(part) for part in item.path),
        ):
            report.add(
                f"schema {label}[{count - 1}] {format_json_path(error.path)}: "
                f"{error.message}"
            )
    return count


def looks_absolute_path(value: str) -> bool:
    """Return whether a serialized value is an absolute local filesystem path."""
    return (
        value.startswith("/")
        or value.startswith("\\\\")
        or value.startswith("//")
        or bool(WINDOWS_ABSOLUTE_PATTERN.match(value))
    )


def scan_absolute_paths(
    payload: Any,
    label: str,
    report: ValidationReport,
    key: str | None = None,
) -> None:
    """Reject absolute paths in path-bearing serialized fields."""
    if isinstance(payload, dict):
        for child_key, value in payload.items():
            scan_absolute_paths(value, f"{label}.{child_key}", report, child_key)
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            scan_absolute_paths(value, f"{label}[{index}]", report, key)
        return
    if not isinstance(payload, str):
        return
    path_key = key is not None and any(
        marker in key.lower()
        for marker in ("path", "root", "alias", "filename", "file_name")
    )
    if path_key and looks_absolute_path(payload):
        report.add(f"absolute path serialized at {label}")


def load_documents(dataset: Path, report: ValidationReport) -> list[dict[str, Any]]:
    """Read every parsed document JSON in stable filename order."""
    directory = dataset / "documents"
    if not directory.is_dir():
        report.add("missing directory: documents")
        return []
    documents: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        payload = read_json(path, report)
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["__validator_filename"] = path.name
            documents.append(payload)
        elif payload is not None:
            report.add(f"{path.name}: document must be an object")
    return documents


def as_dict(payload: Any, label: str, report: ValidationReport) -> dict[str, Any]:
    """Return a JSON object or record a type error."""
    if isinstance(payload, dict):
        return payload
    if payload is not None:
        report.add(f"{label} must contain a JSON object")
    return {}


def compact_text(value: Any) -> str:
    """Normalize PDF whitespace for extractive evidence comparisons."""
    return re.sub(r"\s+", " ", str(value)).strip()


def union_boxes(boxes: list[list[float]]) -> list[float]:
    """Return the union of non-empty PDF-space boxes."""
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def boxes_close(left: Any, right: list[float], tolerance: float = 0.05) -> bool:
    """Compare four-coordinate boxes while allowing JSON rounding noise."""
    return (
        isinstance(left, list)
        and len(left) == 4
        and all(
            isinstance(value, int | float) and abs(float(value) - expected) <= tolerance
            for value, expected in zip(left, right, strict=True)
        )
    )


def validate_dataset(dataset: Path, schemas: Path) -> dict[str, Any]:
    """Validate schemas and cross-file invariants for one generated dataset."""
    report = ValidationReport()
    dataset = dataset.resolve()
    schemas = schemas.resolve()
    report.require(dataset.is_dir(), f"dataset directory does not exist: {dataset}")
    report.require(schemas.is_dir(), f"schema directory does not exist: {schemas}")

    schema_payloads: dict[str, dict[str, Any]] = {}
    validators: dict[str, Draft202012Validator] = {}
    for label, filename in SCHEMA_FILES.items():
        schema = as_dict(read_json(schemas / filename, report), filename, report)
        if schema:
            try:
                Draft202012Validator.check_schema(schema)
                validators[label] = Draft202012Validator(
                    schema, format_checker=FormatChecker()
                )
                schema_payloads[label] = schema
            except Exception as exc:  # jsonschema exposes several schema exceptions
                report.add(f"invalid schema {filename}: {type(exc).__name__}: {exc}")

    manifest = read_jsonl(dataset / "manifest.jsonl", report)
    canonical = read_jsonl(dataset / "canonical_manifest.jsonl", report)
    chunks = read_jsonl(dataset / "chunks.jsonl", report)
    development_chunks = read_jsonl(dataset / "chunks.development.jsonl", report)
    evaluation_corpus_chunks = read_jsonl(
        dataset / "evaluation" / "corpus.chunks.jsonl", report
    )
    works = read_jsonl(dataset / "works.jsonl", report)
    eval_papers = read_jsonl(dataset / "evaluation" / "papers.jsonl", report)
    questions = read_jsonl(dataset / "evaluation" / "questions.silver.jsonl", report)
    duplicate_groups = read_json(dataset / "duplicate_groups.json", report)
    if duplicate_groups is None:
        duplicate_groups = []
    elif not isinstance(duplicate_groups, list):
        report.add("duplicate_groups.json must contain a JSON array")
        duplicate_groups = []
    documents_with_names = load_documents(dataset, report)
    documents = []
    document_filenames: dict[str, str] = {}
    for document in documents_with_names:
        clean = dict(document)
        filename = str(clean.pop("__validator_filename"))
        paper_id = clean.get("paper_id")
        if isinstance(paper_id, str):
            document_filenames[paper_id] = filename
        documents.append(clean)
    summary = as_dict(
        read_json(dataset / "summary.json", report), "summary.json", report
    )
    config = as_dict(
        read_json(dataset / "dataset_config.json", report),
        "dataset_config.json",
        report,
    )

    if "manifest" in validators:
        validate_records(manifest, validators["manifest"], "manifest", report)
        validate_records(canonical, validators["manifest"], "canonical", report)
    if "document" in validators:
        validate_records(documents, validators["document"], "document", report)
    if "chunk" in validators:
        validate_records(chunks, validators["chunk"], "chunk", report)
        validate_records(
            development_chunks, validators["chunk"], "development_chunk", report
        )
        validate_records(
            evaluation_corpus_chunks,
            validators["chunk"],
            "evaluation_corpus_chunk",
            report,
        )
    if "question" in validators:
        validate_records(questions, validators["question"], "question", report)

    serialized_groups = {
        "manifest": manifest,
        "canonical": canonical,
        "works": works,
        "documents": documents,
        "chunks": chunks,
        "development_chunks": development_chunks,
        "evaluation.corpus_chunks": evaluation_corpus_chunks,
        "evaluation.papers": eval_papers,
        "evaluation.questions": questions,
        "duplicate_groups": duplicate_groups,
        "summary": summary,
        "dataset_config": config,
    }
    for label, payload in serialized_groups.items():
        scan_absolute_paths(payload, label, report)

    report.require(
        len(manifest) == summary.get("source_pdf_count"),
        "manifest count does not match summary.source_pdf_count",
    )
    report.require(
        len(canonical) == summary.get("canonical_pdf_count"),
        "canonical count does not match summary.canonical_pdf_count",
    )
    report.require(
        len(works) == summary.get("logical_work_count"),
        "works count does not match summary.logical_work_count",
    )
    report.require(
        len(documents) == summary.get("parsed_document_count"),
        "documents count does not match summary.parsed_document_count",
    )
    report.require(
        len(chunks) == summary.get("chunk_count"),
        "chunk count does not match summary.chunk_count",
    )
    report.require(
        len(development_chunks) == summary.get("development_chunk_count"),
        "development chunks count does not match summary.development_chunk_count",
    )
    report.require(
        len(evaluation_corpus_chunks) == summary.get("evaluation_corpus_chunk_count"),
        "evaluation corpus count does not match summary.evaluation_corpus_chunk_count",
    )
    report.require(
        len(eval_papers) == summary.get("evaluation_paper_count"),
        "evaluation papers count does not match summary.evaluation_paper_count",
    )
    report.require(
        len(questions) == summary.get("evaluation_question_count"),
        "evaluation questions count does not match summary.evaluation_question_count",
    )

    manifest_file_ids = [str(record.get("file_id")) for record in manifest]
    report.require(
        len(set(manifest_file_ids)) == len(manifest_file_ids),
        "manifest file_id values are not unique",
    )
    canonical_ids = [str(record.get("paper_id")) for record in canonical]
    canonical_id_set = set(canonical_ids)
    report.require(
        len(canonical_id_set) == len(canonical_ids),
        "canonical paper_id values are not unique",
    )
    report.require(
        all(record.get("is_exact_duplicate") is False for record in canonical),
        "canonical manifest contains an exact-duplicate record",
    )
    manifest_by_file_id = {str(record.get("file_id")): record for record in manifest}
    expected_canonical_file_ids = {
        str(record.get("file_id"))
        for record in manifest
        if record.get("is_exact_duplicate") is False
    }
    canonical_file_ids = {str(record.get("file_id")) for record in canonical}
    report.require(
        canonical_file_ids == expected_canonical_file_ids,
        "canonical manifest is not the exact non-duplicate manifest subset",
    )
    for record in canonical:
        file_id = str(record.get("file_id"))
        report.require(
            record == manifest_by_file_id.get(file_id),
            f"canonical record differs from manifest record: {file_id}",
        )

    manifest_by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in manifest:
        manifest_by_sha[str(record.get("sha256"))].append(record)
    expected_duplicate_shas = {
        digest for digest, records in manifest_by_sha.items() if len(records) > 1
    }
    duplicate_group_by_sha: dict[str, dict[str, Any]] = {}
    for group in duplicate_groups:
        if not isinstance(group, dict):
            report.add("duplicate group must be an object")
            continue
        digest = str(group.get("sha256"))
        if digest in duplicate_group_by_sha:
            report.add(f"duplicate duplicate-group sha256: {digest}")
        duplicate_group_by_sha[digest] = group
    report.require(
        set(duplicate_group_by_sha) == expected_duplicate_shas,
        "duplicate_groups.json does not exactly match repeated sha256 groups",
    )
    for digest, records in manifest_by_sha.items():
        canonical_records_for_sha = [
            record for record in records if record.get("is_exact_duplicate") is False
        ]
        report.require(
            len(canonical_records_for_sha) == 1,
            f"sha256 does not have exactly one canonical file: {digest}",
        )
        if len(canonical_records_for_sha) != 1:
            continue
        canonical_record = canonical_records_for_sha[0]
        canonical_file_id = canonical_record.get("file_id")
        canonical_path = canonical_record.get("relative_path")
        canonical_paper_id = canonical_record.get("paper_id")
        report.require(
            canonical_record.get("duplicate_of_file_id") is None,
            f"canonical file has duplicate_of_file_id: {canonical_file_id}",
        )
        for record in records:
            file_id = record.get("file_id")
            report.require(
                record.get("canonical_relative_path") == canonical_path,
                f"canonical_relative_path mismatch: {file_id}",
            )
            report.require(
                record.get("paper_id") == canonical_paper_id,
                f"same-sha records have different paper_id: {file_id}",
            )
            if record is canonical_record:
                continue
            report.require(
                record.get("is_exact_duplicate") is True
                and record.get("duplicate_of_file_id") == canonical_file_id
                and record.get("index_policy") == "skip_exact_duplicate"
                and record.get("indexable") is False,
                f"invalid exact-duplicate relationship: {file_id}",
            )
            for field in (
                "work_id",
                "dataset_split",
                "tuning_allowed",
                "translation_of_paper_id",
                "semantic_duplicate_of_paper_id",
            ):
                report.require(
                    record.get(field) == canonical_record.get(field),
                    f"exact duplicate {field} differs from canonical: {file_id}",
                )
        if len(records) > 1:
            group = duplicate_group_by_sha.get(digest)
            if group is not None:
                report.require(
                    group.get("paper_id") == canonical_paper_id
                    and group.get("canonical_relative_path") == canonical_path
                    and group.get("aliases")
                    == sorted(str(record.get("relative_path")) for record in records),
                    f"duplicate group contents mismatch: {digest}",
                )

    canonical_by_paper_id = {
        str(record.get("paper_id")): record for record in canonical
    }
    for record in canonical:
        paper_id = str(record.get("paper_id"))
        translation_target_id = record.get("translation_of_paper_id")
        if record.get("index_policy") == "auxiliary_translation":
            report.require(
                translation_target_id is not None,
                f"auxiliary translation has no original target: {paper_id}",
            )
        if translation_target_id is not None:
            target = canonical_by_paper_id.get(str(translation_target_id))
            report.require(
                target is not None
                and record.get("document_type") == "translation"
                and target.get("document_type") == "original"
                and target.get("work_id") == record.get("work_id"),
                f"invalid translation_of_paper_id relationship: {paper_id}",
            )
        semantic_target_id = record.get("semantic_duplicate_of_paper_id")
        if record.get("index_policy") == "skip_semantic_variant":
            target = canonical_by_paper_id.get(str(semantic_target_id))
            report.require(
                semantic_target_id is not None
                and target is not None
                and target.get("work_id") == record.get("work_id")
                and target.get("paper_id") != record.get("paper_id"),
                f"invalid semantic_duplicate_of_paper_id relationship: {paper_id}",
            )
        else:
            report.require(
                semantic_target_id is None,
                f"non-variant canonical record has semantic duplicate target: {paper_id}",
            )

    document_ids = [str(document.get("paper_id")) for document in documents]
    report.require(
        len(set(document_ids)) == len(document_ids),
        "document paper_id values are not unique",
    )
    report.require(
        set(document_ids) == canonical_id_set,
        "document paper_id set does not match canonical manifest",
    )
    for paper_id, filename in document_filenames.items():
        report.require(
            filename == f"{paper_id}.json",
            f"document filename does not match paper_id: {filename}",
        )
    work_ids = [str(record.get("work_id")) for record in works]
    manifest_work_ids = {str(record.get("work_id")) for record in manifest}
    report.require(
        len(set(work_ids)) == len(work_ids), "works work_id values are not unique"
    )
    report.require(
        set(work_ids) == manifest_work_ids,
        "works work_id set does not match manifest",
    )

    splits_by_work: dict[str, set[str]] = defaultdict(set)
    tuning_by_work: dict[str, set[bool]] = defaultdict(set)
    for record in manifest:
        work_id = str(record.get("work_id"))
        splits_by_work[work_id].add(str(record.get("dataset_split")))
        if isinstance(record.get("tuning_allowed"), bool):
            tuning_by_work[work_id].add(bool(record["tuning_allowed"]))
        if record.get("dataset_split") == "test":
            report.require(
                record.get("tuning_allowed") is False,
                f"test manifest record allows tuning: {record.get('file_id')}",
            )
    for work_id, splits in splits_by_work.items():
        report.require(
            len(splits) == 1,
            f"work_id crosses dataset splits: {work_id}: {sorted(splits)}",
        )
    for work_id, values in tuning_by_work.items():
        report.require(
            len(values) == 1,
            f"work_id has inconsistent tuning_allowed: {work_id}",
        )
    for work in works:
        if work.get("dataset_split") == "test":
            report.require(
                work.get("tuning_allowed") is False,
                f"test work allows tuning: {work.get('work_id')}",
            )
    held_out_work_ids = {
        work_id for work_id, splits in splits_by_work.items() if splits == {"test"}
    }
    eval_work_ids: set[str] = set()
    eval_paper_id_values = [str(paper.get("paper_id")) for paper in eval_papers]
    report.require(
        len(eval_paper_id_values) == len(set(eval_paper_id_values)),
        "evaluation paper_id values are not unique",
    )
    for paper in eval_papers:
        work_id = str(paper.get("work_id"))
        eval_work_ids.add(work_id)
        paper_id = str(paper.get("paper_id"))
        canonical_record = canonical_by_paper_id.get(paper_id)
        report.require(
            canonical_record is not None
            and canonical_record.get("work_id") == paper.get("work_id")
            and canonical_record.get("dataset_split") == "test",
            f"evaluation paper does not match a canonical test record: {paper_id}",
        )
        report.require(
            work_id in held_out_work_ids,
            f"evaluation paper is not in test split: {paper.get('paper_id')}",
        )
        report.require(
            paper.get("split") == "test",
            f"evaluation paper is not labelled test: {paper.get('paper_id')}",
        )
        report.require(
            paper.get("tuning_allowed") is False,
            f"evaluation paper allows tuning: {paper.get('paper_id')}",
        )
    report.require(
        eval_work_ids == held_out_work_ids,
        "evaluation paper work_ids do not exactly match held-out work_ids",
    )

    canonical_by_id = {str(record.get("paper_id")): record for record in canonical}
    document_by_id = {str(document.get("paper_id")): document for document in documents}
    chunks_by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunk_by_id: dict[str, dict[str, Any]] = {}
    max_chunk_chars = config.get("max_chunk_chars")
    report.require(
        not isinstance(max_chunk_chars, bool)
        and isinstance(max_chunk_chars, int)
        and max_chunk_chars >= 400,
        "dataset_config.max_chunk_chars must be an integer of at least 400",
    )
    for chunk in chunks:
        paper_id = str(chunk.get("paper_id"))
        chunk_id = str(chunk.get("chunk_id"))
        chunks_by_paper[paper_id].append(chunk)
        if chunk_id in chunk_by_id:
            report.add(f"duplicate chunk_id: {chunk_id}")
        chunk_by_id[chunk_id] = chunk
        text = chunk.get("text")
        char_count = chunk.get("char_count")
        report.require(
            isinstance(text, str) and char_count == len(text),
            f"chunk char_count does not match text length: {chunk_id}",
        )
        report.require(
            isinstance(char_count, int)
            and not isinstance(char_count, bool)
            and isinstance(max_chunk_chars, int)
            and char_count <= max_chunk_chars,
            f"chunk exceeds dataset_config.max_chunk_chars: {chunk_id}",
        )
        if isinstance(text, str):
            expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            report.require(
                chunk.get("content_sha256") == expected_hash,
                f"chunk content_sha256 does not match text: {chunk_id}",
            )
        canonical_record = canonical_by_id.get(paper_id)
        report.require(
            canonical_record is not None,
            f"chunk does not link to a canonical paper: {chunk_id}",
        )
        if canonical_record is not None:
            report.require(
                chunk.get("work_id") == canonical_record.get("work_id"),
                f"chunk work_id does not match canonical paper: {chunk_id}",
            )
            for field in (
                "dataset_split",
                "tuning_allowed",
                "indexable",
                "index_policy",
            ):
                report.require(
                    chunk.get(field) == canonical_record.get(field),
                    f"chunk {field} does not match canonical paper: {chunk_id}",
                )
        document = document_by_id.get(paper_id)
        report.require(
            document is not None,
            f"chunk does not link to a parsed document: {chunk_id}",
        )
        if document is not None:
            page_number = chunk.get("page_number")
            report.require(
                isinstance(page_number, int)
                and 1 <= page_number <= int(document.get("pages_count", 0)),
                f"chunk page_number is invalid: {chunk_id}",
            )
    development_ids = [str(chunk.get("chunk_id")) for chunk in development_chunks]
    evaluation_corpus_ids = [
        str(chunk.get("chunk_id")) for chunk in evaluation_corpus_chunks
    ]
    report.require(
        len(development_ids) == len(set(development_ids)),
        "development chunk ids are not unique",
    )
    report.require(
        len(evaluation_corpus_ids) == len(set(evaluation_corpus_ids)),
        "evaluation corpus chunk ids are not unique",
    )
    report.require(
        set(development_ids).isdisjoint(evaluation_corpus_ids),
        "development and evaluation corpus chunks overlap",
    )
    expected_development_ids = {
        chunk_id
        for chunk_id, chunk in chunk_by_id.items()
        if chunk.get("dataset_split") == "development"
        and chunk.get("indexable") is True
    }
    expected_evaluation_ids = {
        chunk_id
        for chunk_id, chunk in chunk_by_id.items()
        if chunk.get("dataset_split") == "test" and chunk.get("indexable") is True
    }
    report.require(
        set(development_ids) == expected_development_ids,
        "chunks.development.jsonl is not the exact development/indexable partition",
    )
    report.require(
        set(evaluation_corpus_ids) == expected_evaluation_ids,
        "evaluation corpus is not the exact test/indexable partition",
    )
    for label, isolated_chunks, expected_split, expected_tuning in (
        ("development", development_chunks, "development", True),
        ("evaluation", evaluation_corpus_chunks, "test", False),
    ):
        for chunk in isolated_chunks:
            chunk_id = str(chunk.get("chunk_id"))
            report.require(
                chunk == chunk_by_id.get(chunk_id),
                f"{label} chunk differs from chunks.jsonl: {chunk_id}",
            )
            report.require(
                chunk.get("dataset_split") == expected_split
                and chunk.get("tuning_allowed") is expected_tuning
                and chunk.get("indexable") is True,
                f"{label} chunk has invalid isolation metadata: {chunk_id}",
            )

    for paper_id, document in document_by_id.items():
        report.require(
            len(chunks_by_paper.get(paper_id, [])) == document.get("chunk_count"),
            f"document chunk_count mismatch: {paper_id}",
        )
        canonical_record = canonical_by_id.get(paper_id)
        if canonical_record is not None:
            for field in (
                "work_id",
                "dataset_split",
                "tuning_allowed",
                "indexable",
                "index_policy",
            ):
                report.require(
                    document.get(field) == canonical_record.get(field),
                    f"document {field} does not match canonical paper: {paper_id}",
                )
        parser = document.get("parser")
        report.require(
            isinstance(parser, dict)
            and parser.get("max_chunk_chars") == max_chunk_chars,
            f"document parser max_chunk_chars mismatch: {paper_id}",
        )
    for chunk_id, chunk in chunk_by_id.items():
        previous_id = chunk.get("previous_chunk_id")
        next_id = chunk.get("next_chunk_id")
        if previous_id is not None:
            previous = chunk_by_id.get(str(previous_id))
            report.require(
                previous is not None, f"unknown previous_chunk_id: {chunk_id}"
            )
            if previous is not None:
                report.require(
                    previous.get("next_chunk_id") == chunk_id,
                    f"non-reciprocal previous_chunk_id: {chunk_id}",
                )
        if next_id is not None:
            following = chunk_by_id.get(str(next_id))
            report.require(following is not None, f"unknown next_chunk_id: {chunk_id}")
            if following is not None:
                report.require(
                    following.get("previous_chunk_id") == chunk_id,
                    f"non-reciprocal next_chunk_id: {chunk_id}",
                )

    eval_paper_ids = {str(paper.get("paper_id")) for paper in eval_papers}
    for question in questions:
        question_id = question.get("question_id")
        paper_id = str(question.get("paper_id"))
        document = document_by_id.get(paper_id)
        report.require(
            paper_id in eval_paper_ids,
            f"evaluation question paper is not in papers.jsonl: {question_id}",
        )
        report.require(
            document is not None,
            f"evaluation question has no parsed document: {question_id}",
        )
        if document is None:
            continue
        report.require(
            question.get("work_id") == document.get("work_id"),
            f"evaluation question work_id mismatch: {question_id}",
        )
        report.require(
            str(question.get("work_id")) in held_out_work_ids,
            f"evaluation question is not held out: {question_id}",
        )
        evidence = question.get("evidence")
        if not isinstance(evidence, dict):
            report.add(f"evaluation question evidence is not an object: {question_id}")
            continue
        page_number = evidence.get("page_number")
        valid_page = (
            isinstance(page_number, int)
            and not isinstance(page_number, bool)
            and 1 <= page_number <= int(document.get("pages_count", 0))
        )
        report.require(
            valid_page,
            f"evaluation evidence page_number is invalid: {question_id}",
        )
        if not valid_page:
            continue
        page = document["pages"][page_number - 1]
        report.require(
            page.get("page_number") == page_number,
            f"document page order mismatch for evaluation evidence: {question_id}",
        )
        block_ids = evidence.get("block_ids")
        if not isinstance(block_ids, list) or not all(
            isinstance(block_id, str) for block_id in block_ids
        ):
            report.add(f"evaluation evidence block_ids are invalid: {question_id}")
            continue
        blocks_by_id = {
            str(block.get("block_id")): block for block in page.get("text_blocks", [])
        }
        evidence_blocks = [
            blocks_by_id[block_id] for block_id in block_ids if block_id in blocks_by_id
        ]
        report.require(
            len(evidence_blocks) == len(block_ids),
            f"evaluation evidence references unknown page block: {question_id}",
        )
        if len(evidence_blocks) != len(block_ids):
            continue
        answer_text = compact_text(question.get("answer"))
        evidence_text = compact_text(evidence.get("text"))
        referenced_text = compact_text(
            "\n".join(str(block.get("text", "")) for block in evidence_blocks)
        )
        report.require(
            answer_text == evidence_text,
            f"evaluation answer differs from evidence text: {question_id}",
        )
        report.require(
            bool(evidence_text) and evidence_text in referenced_text,
            f"evaluation evidence text is not extractive from referenced blocks: {question_id}",
        )
        boxes = [block.get("bbox") for block in evidence_blocks]
        valid_boxes = all(
            isinstance(box, list)
            and len(box) == 4
            and all(isinstance(value, int | float) for value in box)
            for box in boxes
        )
        report.require(
            valid_boxes,
            f"evaluation evidence block bbox is invalid: {question_id}",
        )
        if valid_boxes:
            expected_bbox = union_boxes(boxes)
            report.require(
                boxes_close(evidence.get("bbox"), expected_bbox),
                f"evaluation evidence bbox does not match referenced blocks: {question_id}",
            )
            width = max(float(page.get("width", 0.0)), 1.0)
            height = max(float(page.get("height", 0.0)), 1.0)
            expected_normalized_bbox = [
                max(0.0, min(1.0, expected_bbox[0] / width)),
                max(0.0, min(1.0, expected_bbox[1] / height)),
                max(0.0, min(1.0, expected_bbox[2] / width)),
                max(0.0, min(1.0, expected_bbox[3] / height)),
            ]
            report.require(
                boxes_close(
                    evidence.get("bbox_normalized_top_left"),
                    expected_normalized_bbox,
                    tolerance=0.000002,
                ),
                f"evaluation normalized bbox does not match raw bbox: {question_id}",
            )

    report.require(
        config.get("source_integrity_verified") is True,
        "dataset_config.source_integrity_verified is not true",
    )
    report.require(
        summary.get("source_integrity_verified") is True,
        "summary.source_integrity_verified is not true",
    )

    counts = {
        "manifest": len(manifest),
        "canonical": len(canonical),
        "works": len(works),
        "documents": len(documents),
        "chunks": len(chunks),
        "development_chunks": len(development_chunks),
        "evaluation_corpus_chunks": len(evaluation_corpus_chunks),
        "evaluation_papers": len(eval_papers),
        "evaluation_questions": len(questions),
        "schemas": len(schema_payloads),
    }
    return {
        "valid": not report.errors,
        "counts": counts,
        "error_count": len(report.errors),
        "errors": report.errors[:MAX_REPORTED_ERRORS],
        "errors_truncated": len(report.errors) > MAX_REPORTED_ERRORS,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate a generated ScholarMind paper dataset."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--schemas", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run validation and emit a concise machine-readable report."""
    args = parse_args(argv)
    report = validate_dataset(args.dataset, args.schemas)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
