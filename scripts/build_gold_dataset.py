#!/usr/bin/env python3
"""Build a private, human-verified Gold release from resolved Silver reviews."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

ANNOTATION_SPEC = "docs/evaluation/paper-dataset/silver-to-gold.md"
MINIMUM_RECHECK_INTERVAL = timedelta(hours=24)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate resolved human reviews, recompute evidence locators, and "
            "build a private Gold JSONL release."
        )
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--schemas", type=Path, default=Path("evaluation/schemas"))
    parser.add_argument("--gold-version", default="paper-gold-v1")
    parser.add_argument(
        "--replace-generated",
        action="store_true",
        help="Replace only previously generated review/gold aggregate files.",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read JSONL {path}: {type(exc).__name__}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"{path}:{line_number}: blank JSONL line")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}:{line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(payload)
    if not rows:
        raise ValueError(f"{path}: no records found")
    return tuple(rows)


def _validator(path: Path) -> Draft202012Validator:
    schema = _read_json(path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_schema(
    record: dict[str, Any],
    validator: Draft202012Validator,
    *,
    location: str,
) -> None:
    errors = sorted(
        validator.iter_errors(record),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if not errors:
        return
    error = errors[0]
    path = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.path
    )
    raise ValueError(f"{location} {path}: {error.message}")


def _parse_timestamp(value: Any, *, location: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location}: timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{location}: invalid RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{location}: timestamp must include a timezone")
    return parsed


def _annotation_id(release: str, question_id: str) -> str:
    digest = hashlib.sha256(f"{release}\0{question_id}".encode()).hexdigest()[:16]
    return f"annotation-{digest}"


def _gold_id(gold_version: str, question_id: str) -> str:
    digest = hashlib.sha256(f"{gold_version}\0{question_id}".encode()).hexdigest()[:16]
    return f"gold-{digest}"


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip()


def _verify_frozen_inputs(
    dataset: Path,
    workspace: Path,
) -> tuple[dict[str, Any], str, str, set[str]]:
    manifest = _read_json(workspace / "frozen/input-manifest.json")
    checksums_path = workspace / "frozen/source_checksums.sha256"
    questions_path = dataset / "evaluation/questions.silver.jsonl"
    if not checksums_path.is_file() or not questions_path.is_file():
        raise FileNotFoundError("frozen checksums or Silver questions are missing")
    silver_sha = _sha256(questions_path)
    checksums_sha = _sha256(checksums_path)
    if silver_sha != manifest.get("questions_silver_file_sha256"):
        raise ValueError("questions.silver.jsonl changed after review preparation")
    if checksums_sha != manifest.get("source_checksums_file_sha256"):
        raise ValueError("source_checksums.sha256 changed after review preparation")

    seen_paths: set[str] = set()
    for line_number, line in enumerate(
        checksums_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(
                f"source_checksums.sha256:{line_number}: invalid checksum line"
            )
        expected, relative = match.groups()
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(
                f"source_checksums.sha256:{line_number}: unsafe relative path"
            )
        if relative in seen_paths:
            raise ValueError(f"duplicate frozen checksum path: {relative}")
        seen_paths.add(relative)
        source_path = dataset / relative_path
        if not source_path.is_file() or _sha256(source_path) != expected:
            raise ValueError(f"frozen source changed or is missing: {relative}")
    if "evaluation/questions.silver.jsonl" not in seen_paths:
        raise ValueError("Silver questions are missing from the frozen checksum list")
    return manifest, silver_sha, checksums_sha, seen_paths


def _load_questions(
    dataset: Path,
    validator: Draft202012Validator,
) -> dict[str, dict[str, Any]]:
    rows = _read_jsonl(dataset / "evaluation/questions.silver.jsonl")
    questions: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        _validate_schema(row, validator, location=f"Silver[{index}]")
        question_id = str(row["question_id"])
        if question_id in questions:
            raise ValueError(f"duplicate Silver question_id: {question_id}")
        questions[question_id] = row
    return questions


def _load_documents(
    dataset: Path,
) -> dict[str, tuple[dict[str, Any], str]]:
    directory = dataset / "documents"
    if not directory.is_dir():
        raise FileNotFoundError("dataset documents directory is missing")
    documents: dict[str, tuple[dict[str, Any], str]] = {}
    for path in sorted(directory.glob("paper-*.json")):
        document = _read_json(path)
        paper_id = document.get("paper_id")
        if not isinstance(paper_id, str):
            raise ValueError(f"{path}: paper_id is missing")
        if paper_id in documents:
            raise ValueError(f"duplicate parsed document paper_id: {paper_id}")
        documents[paper_id] = (document, path.relative_to(dataset).as_posix())
    if not documents:
        raise ValueError("dataset contains no parsed documents")
    return documents


def _load_reviews(
    workspace: Path,
    validator: Draft202012Validator,
) -> dict[str, dict[str, Any]]:
    directory = workspace / "reviews/records"
    if not directory.is_dir():
        raise FileNotFoundError("review records directory is missing")
    reviews: dict[str, dict[str, Any]] = {}
    annotation_ids: set[str] = set()
    for path in sorted(directory.glob("annotation-*.json")):
        record = _read_json(path)
        _validate_schema(record, validator, location=path.name)
        question_id = str(record["source"]["question_id"])
        annotation_id = str(record["annotation_record_id"])
        if question_id in reviews:
            raise ValueError(f"duplicate review question_id: {question_id}")
        if annotation_id in annotation_ids:
            raise ValueError(f"duplicate annotation_record_id: {annotation_id}")
        reviews[question_id] = record
        annotation_ids.add(annotation_id)
    if not reviews:
        raise ValueError("workspace contains no review records")
    return reviews


def _revision_is_empty(revision: dict[str, Any]) -> bool:
    evidence = revision["evidence"]
    return (
        revision["question_type"] is None
        and revision["question"] is None
        and revision["answer"] is None
        and revision["acceptable_answers"] == []
        and evidence["page_number"] is None
        and evidence["text"] is None
        and evidence["block_ids"] == []
        and evidence["bbox"] is None
        and evidence["bbox_normalized_top_left"] is None
    )


def _require_complete_revision(
    revision: dict[str, Any],
    *,
    location: str,
) -> None:
    for key in ("question_type", "question", "answer"):
        value = revision[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{location}.{key} must be complete")
    if revision["acceptable_answers"] != []:
        raise ValueError(f"{location}.acceptable_answers must remain empty in v1")
    evidence = revision["evidence"]
    if not isinstance(evidence["text"], str) or not evidence["text"].strip():
        raise ValueError(f"{location}.evidence.text must be complete")
    if not evidence["block_ids"]:
        raise ValueError(f"{location}.evidence.block_ids must be complete")


def _validate_review_round(round_data: dict[str, Any], *, location: str) -> datetime:
    alias = round_data["reviewer_alias"]
    decision = round_data["decision"]
    confidence = round_data["confidence"]
    checks = tuple(round_data["checks"].values())
    issues = round_data["issue_codes"]
    notes = round_data["notes"]
    revision = round_data["proposed_revision"]
    if not isinstance(alias, str) or not alias.strip():
        raise ValueError(f"{location}.reviewer_alias is required")
    if decision is None or confidence is None or any(value is None for value in checks):
        raise ValueError(f"{location}: decision, checks, and confidence are required")
    reviewed_at = _parse_timestamp(
        round_data["reviewed_at_utc"], location=f"{location}.reviewed_at_utc"
    )
    if decision == "keep":
        if not all(checks) or issues or not _revision_is_empty(revision):
            raise ValueError(
                f"{location}: keep requires all checks true, no issues, no revision"
            )
    elif decision == "edit":
        if all(checks) or not issues:
            raise ValueError(f"{location}: edit requires a failed check and issue code")
        _require_complete_revision(revision, location=f"{location}.proposed_revision")
    elif decision in {"reject", "needs_adjudication"}:
        if not issues or not isinstance(notes, str) or not notes.strip():
            raise ValueError(f"{location}: {decision} requires issues and notes")
        if decision == "reject" and not _revision_is_empty(revision):
            raise ValueError(f"{location}: reject must not carry a revision")
    if "OTHER" in issues and (not isinstance(notes, str) or not notes.strip()):
        raise ValueError(f"{location}: OTHER requires explanatory notes")
    return reviewed_at


def _validate_resolution(
    record: dict[str, Any],
    *,
    location: str,
) -> tuple[datetime, tuple[str, ...]]:
    if record["record_status"] != "resolved":
        raise ValueError(f"{location}: record_status must be resolved")
    first = record["reviews"]["round_1"]
    second = record["reviews"]["round_2"]
    first_at = _validate_review_round(first, location=f"{location}.round_1")
    second_at = _validate_review_round(second, location=f"{location}.round_2")
    if second_at < first_at:
        raise ValueError(f"{location}: round_2 predates round_1")
    first_alias = str(first["reviewer_alias"])
    second_alias = str(second["reviewer_alias"])
    protocol = record["review_protocol"]
    if protocol == "single_reviewer_interval_recheck":
        if first_alias != second_alias:
            raise ValueError(f"{location}: single-reviewer aliases must match")
        if second_at - first_at < MINIMUM_RECHECK_INTERVAL:
            raise ValueError(f"{location}: single-reviewer recheck must wait 24 hours")
    elif protocol == "independent_two_reviewer":
        if first_alias == second_alias:
            raise ValueError(f"{location}: independent reviewers must differ")
    else:
        raise ValueError(f"{location}: review_protocol is required")

    resolution = record["resolution"]
    status = resolution["status"]
    decision = resolution["final_decision"]
    payload_source = resolution["final_payload_source"]
    if status not in {"not_required", "resolved"} or decision is None:
        raise ValueError(f"{location}: final resolution is incomplete")
    resolved_at = _parse_timestamp(
        resolution["resolved_at_utc"], location=f"{location}.resolved_at_utc"
    )
    if resolved_at < second_at:
        raise ValueError(f"{location}: resolution predates round_2")
    expected_source = {"keep": "silver", "edit": "final_revision", "reject": "none"}
    if payload_source != expected_source[decision]:
        raise ValueError(f"{location}: final_payload_source conflicts with decision")
    if decision == "edit":
        _require_complete_revision(
            resolution["final_revision"], location=f"{location}.final_revision"
        )
    elif not _revision_is_empty(resolution["final_revision"]):
        raise ValueError(f"{location}: non-edit resolution must not carry a revision")

    if status == "not_required":
        if first["decision"] != second["decision"] or decision != first["decision"]:
            raise ValueError(f"{location}: disagreement requires adjudication")
        if decision == "edit" and (
            first["proposed_revision"] != second["proposed_revision"]
            or resolution["final_revision"] != first["proposed_revision"]
        ):
            raise ValueError(f"{location}: differing edits require adjudication")
    else:
        if not isinstance(resolution["resolver_alias"], str) or not str(
            resolution["resolver_alias"]
        ).strip():
            raise ValueError(f"{location}: adjudication requires resolver_alias")
        if not isinstance(resolution["rationale"], str) or not str(
            resolution["rationale"]
        ).strip():
            raise ValueError(f"{location}: adjudication requires rationale")
    return resolved_at, tuple(sorted({first_alias, second_alias}))


def _union_boxes(boxes: Iterable[list[float]]) -> list[float]:
    values = list(boxes)
    return [
        round(min(box[0] for box in values), 2),
        round(min(box[1] for box in values), 2),
        round(max(box[2] for box in values), 2),
        round(max(box[3] for box in values), 2),
    ]


def _boxes_close(left: Any, right: list[float], tolerance: float = 0.05) -> bool:
    return (
        isinstance(left, list)
        and len(left) == 4
        and all(
            isinstance(value, int | float) and abs(float(value) - expected) <= tolerance
            for value, expected in zip(left, right, strict=True)
        )
    )


def _recompute_evidence(
    evidence: dict[str, Any],
    document: dict[str, Any],
    *,
    location: str,
) -> dict[str, Any]:
    selected_ids = evidence["block_ids"]
    if not selected_ids:
        raise ValueError(f"{location}.block_ids must not be empty")
    blocks: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for page in document.get("pages", []):
        for block in page.get("text_blocks", []):
            block_id = str(block.get("block_id"))
            if block_id in blocks:
                raise ValueError(f"{location}: duplicate parsed block_id {block_id}")
            blocks[block_id] = (page, block)
    missing = [block_id for block_id in selected_ids if block_id not in blocks]
    if missing:
        raise ValueError(f"{location}: unknown block_ids: {', '.join(missing)}")
    selected = [blocks[block_id] for block_id in selected_ids]
    page_numbers = {int(page["page_number"]) for page, _ in selected}
    if len(page_numbers) != 1:
        raise ValueError(f"{location}: evidence blocks must be on one page")
    page_number = page_numbers.pop()
    page = selected[0][0]
    ordered_blocks = sorted(
        (block for _, block in selected),
        key=lambda block: int(block["reading_order"]),
    )
    canonical_text = _compact_text(" ".join(block["text"] for block in ordered_blocks))
    if _compact_text(evidence["text"]) != canonical_text:
        raise ValueError(f"{location}: evidence text does not match selected blocks")
    provided_page = evidence.get("page_number")
    if provided_page is not None and provided_page != page_number:
        raise ValueError(f"{location}: provided page does not match selected blocks")
    bbox = _union_boxes([list(block["bbox"]) for block in ordered_blocks])
    provided_bbox = evidence.get("bbox")
    if provided_bbox is not None and not _boxes_close(provided_bbox, bbox):
        raise ValueError(f"{location}: provided bbox does not match selected blocks")
    width = float(page["width"])
    height = float(page["height"])
    normalized = [
        round(max(0.0, min(1.0, bbox[0] / width)), 6),
        round(max(0.0, min(1.0, bbox[1] / height)), 6),
        round(max(0.0, min(1.0, bbox[2] / width)), 6),
        round(max(0.0, min(1.0, bbox[3] / height)), 6),
    ]
    provided_normalized = evidence.get("bbox_normalized_top_left")
    if provided_normalized is not None and not _boxes_close(
        provided_normalized, normalized, tolerance=0.00001
    ):
        raise ValueError(
            f"{location}: provided normalized bbox does not match selected blocks"
        )
    return {
        "page_number": page_number,
        "text": canonical_text,
        "block_ids": [block["block_id"] for block in ordered_blocks],
        "bbox": bbox,
        "bbox_normalized_top_left": normalized,
    }


def _expected_gold_export(decision: str, gold_id: str | None) -> dict[str, Any]:
    if decision == "reject":
        return {
            "eligible": False,
            "gold_question_id": None,
            "label_quality": None,
            "review_status": None,
            "derivation": None,
        }
    corrected = decision == "edit"
    return {
        "eligible": True,
        "gold_question_id": gold_id,
        "label_quality": "human_verified_gold",
        "review_status": "corrected" if corrected else "accepted",
        "derivation": "corrected" if corrected else "unchanged",
    }


def _export_was_filled(export: dict[str, Any]) -> bool:
    return bool(export["eligible"]) or any(
        export[key] is not None
        for key in (
            "gold_question_id",
            "label_quality",
            "review_status",
            "derivation",
        )
    )


def _build_record(
    question: dict[str, Any],
    review: dict[str, Any],
    document: dict[str, Any],
    *,
    release: str,
    gold_version: str,
    silver_sha: str,
    checksums_sha: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    question_id = str(question["question_id"])
    location = f"review[{question_id}]"
    source = review["source"]
    expected_source = {
        "dataset_release": release,
        "question_id": question_id,
        "paper_id": question["paper_id"],
        "work_id": question["work_id"],
        "questions_silver_file_sha256": silver_sha,
        "source_checksums_file_sha256": checksums_sha,
    }
    if source != expected_source:
        raise ValueError(f"{location}: frozen source identity mismatch")
    if review["annotation_record_id"] != _annotation_id(release, question_id):
        raise ValueError(f"{location}: annotation_record_id is not release-stable")
    if document.get("paper_id") != question["paper_id"] or document.get(
        "work_id"
    ) != question["work_id"]:
        raise ValueError(f"{location}: parsed document identity mismatch")
    resolved_at, aliases = _validate_resolution(review, location=location)
    decision = str(review["resolution"]["final_decision"])
    gold_id = None if decision == "reject" else _gold_id(gold_version, question_id)
    expected_export = _expected_gold_export(decision, gold_id)
    if _export_was_filled(review["gold_export"]) and review["gold_export"] != expected_export:
        raise ValueError(f"{location}: prefilled gold_export conflicts with resolution")
    exported_review = copy.deepcopy(review)
    exported_review["gold_export"] = expected_export
    if decision == "reject":
        return None, exported_review

    if decision == "keep":
        payload = {
            "question_type": question["question_type"],
            "question": question["question"],
            "answer": question["answer"],
            "acceptable_answers": [],
            "evidence": question["evidence"],
        }
    else:
        payload = review["resolution"]["final_revision"]
    if payload["question_type"] != question["question_type"]:
        raise ValueError(f"{location}: v1 edits cannot change question_type")
    evidence = _recompute_evidence(
        payload["evidence"], document, location=f"{location}.evidence"
    )
    if _compact_text(payload["answer"]) != evidence["text"]:
        raise ValueError(f"{location}: answer must equal extractive evidence text")
    if payload["acceptable_answers"] != []:
        raise ValueError(f"{location}: acceptable_answers must remain empty in v1")
    resolution = review["resolution"]
    gold = {
        "schema_version": "1.0.0",
        "annotation_spec_version": "1.0",
        "gold_version": gold_version,
        "gold_question_id": gold_id,
        "source_question_id": question_id,
        "paper_id": question["paper_id"],
        "work_id": question["work_id"],
        "question_type": payload["question_type"],
        "question": _compact_text(payload["question"]),
        "answer": evidence["text"],
        "acceptable_answers": [],
        "evidence": evidence,
        "label_quality": "human_verified_gold",
        "review_status": expected_export["review_status"],
        "derivation": expected_export["derivation"],
        "tuning_allowed": False,
        "provenance": {
            "annotation_spec": ANNOTATION_SPEC,
            "source_dataset_release": release,
            "questions_silver_file_sha256": silver_sha,
            "source_checksums_file_sha256": checksums_sha,
            "review_protocol": review["review_protocol"],
            "reviewer_count": len(aliases),
            "reviewer_aliases": list(aliases),
            "source_review_record_id": review["annotation_record_id"],
            "resolution_status": resolution["status"],
            "resolver_alias": resolution["resolver_alias"],
            "resolved_at_utc": resolved_at.isoformat(),
        },
    }
    return gold, exported_review


def _serialize_jsonl(rows: Iterable[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def build_gold_release(
    dataset: Path,
    workspace: Path,
    schemas: Path,
    *,
    gold_version: str,
    replace_generated: bool = False,
) -> dict[str, Any]:
    """Validate all private inputs and atomically build aggregate review/Gold files."""
    dataset = dataset.expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    schemas = schemas.expanduser().resolve()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", gold_version):
        raise ValueError("gold version contains unsafe characters")
    if not dataset.is_dir() or not workspace.is_dir() or not schemas.is_dir():
        raise FileNotFoundError("dataset, workspace, and schemas must exist")

    review_output = workspace / "reviews/questions.review.jsonl"
    gold_output = workspace / "gold/questions.gold.jsonl"
    existing = [path for path in (review_output, gold_output) if path.exists()]
    if existing and not replace_generated:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(
            f"generated outputs already exist ({names}); use --replace-generated"
        )

    manifest, silver_sha, checksums_sha, frozen_paths = _verify_frozen_inputs(
        dataset, workspace
    )
    question_validator = _validator(schemas / "paper_eval_question.schema.json")
    review_validator = _validator(schemas / "paper_review.schema.json")
    gold_validator = _validator(schemas / "paper_gold_question.schema.json")
    questions = _load_questions(dataset, question_validator)
    documents = _load_documents(dataset)
    reviews = _load_reviews(workspace, review_validator)
    if set(reviews) != set(questions):
        missing = sorted(set(questions) - set(reviews))
        extra = sorted(set(reviews) - set(questions))
        raise ValueError(
            f"review/Silver question sets differ; missing={missing}, extra={extra}"
        )
    release = manifest.get("dataset_release")
    if not isinstance(release, str) or not release:
        raise ValueError("input manifest dataset_release is missing")

    gold_rows: list[dict[str, Any]] = []
    exported_reviews: list[dict[str, Any]] = []
    decision_counts: Counter[str] = Counter()
    seen_gold_ids: set[str] = set()
    for question_id in sorted(questions):
        question = questions[question_id]
        paper_id = str(question["paper_id"])
        if paper_id not in documents:
            raise ValueError(f"missing parsed document for {paper_id}")
        document, document_path = documents[paper_id]
        if document_path not in frozen_paths:
            raise ValueError(f"parsed document is not frozen: {document_path}")
        gold, exported_review = _build_record(
            question,
            reviews[question_id],
            document,
            release=release,
            gold_version=gold_version,
            silver_sha=silver_sha,
            checksums_sha=checksums_sha,
        )
        decision = str(exported_review["resolution"]["final_decision"])
        decision_counts[decision] += 1
        exported_reviews.append(exported_review)
        if gold is None:
            continue
        _validate_schema(gold, gold_validator, location=f"Gold[{question_id}]")
        gold_id = str(gold["gold_question_id"])
        if gold_id in seen_gold_ids:
            raise ValueError(f"duplicate gold_question_id: {gold_id}")
        seen_gold_ids.add(gold_id)
        gold_rows.append(gold)

    if len(gold_rows) != decision_counts["keep"] + decision_counts["edit"]:
        raise AssertionError("Gold count invariant failed")
    review_text = _serialize_jsonl(exported_reviews)
    gold_text = _serialize_jsonl(gold_rows)
    built_at = datetime.now(UTC).isoformat()
    build_manifest = {
        **manifest,
        "status": "built",
        "gold_version": gold_version,
        "built_at_utc": built_at,
        "builder_git_commit": _git_commit(),
        "review_schema": "paper_review.schema.json@1.0.0",
        "gold_schema": "paper_gold_question.schema.json@1.0.0",
        "review_count": len(exported_reviews),
        "decision_counts": dict(sorted(decision_counts.items())),
        "gold_question_count": len(gold_rows),
        "gold_work_count": len({row["work_id"] for row in gold_rows}),
        "questions_review_file_sha256": hashlib.sha256(review_text.encode()).hexdigest(),
        "questions_gold_file_sha256": hashlib.sha256(gold_text.encode()).hexdigest(),
    }
    summary = (
        "# Silver review summary\n\n"
        f"- Release: `{release}`\n"
        f"- Gold version: `{gold_version}`\n"
        f"- Built at: `{built_at}`\n"
        "- Status: built from fully resolved human reviews\n"
        f"- Silver questions: {len(questions)}\n"
        f"- Keep: {decision_counts['keep']}\n"
        f"- Edit: {decision_counts['edit']}\n"
        f"- Reject: {decision_counts['reject']}\n"
        f"- Gold questions: {len(gold_rows)}\n"
        f"- Gold work coverage: {build_manifest['gold_work_count']}\n"
        "- Content policy: aggregate counts only; no question or evidence text\n"
    )

    _atomic_write(review_output, review_text)
    _atomic_write(gold_output, gold_text)
    _atomic_write(
        workspace / "build_manifest.json",
        json.dumps(build_manifest, ensure_ascii=False, indent=2) + "\n",
    )
    _atomic_write(workspace / "review_summary.md", summary)
    return {
        "dataset_release": release,
        "gold_version": gold_version,
        "review_count": len(exported_reviews),
        "decision_counts": dict(sorted(decision_counts.items())),
        "gold_question_count": len(gold_rows),
        "gold_work_count": build_manifest["gold_work_count"],
        "content_policy": "stdout and summary contain aggregate counts only",
    }


def main(argv: list[str] | None = None) -> int:
    """Run the fail-closed Gold builder CLI."""
    args = _parser().parse_args(argv)
    result = build_gold_release(
        args.dataset,
        args.workspace,
        args.schemas,
        gold_version=args.gold_version,
        replace_generated=args.replace_generated,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
