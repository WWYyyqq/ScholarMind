"""Tests for the fail-closed Silver-to-Gold builder."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.build_gold_dataset import (
    _annotation_id,
    _gold_id,
    build_gold_release,
)

SCHEMAS = Path(__file__).parents[2] / "evaluation/schemas"
PAPER_ID = "paper-1111111111111111"
WORK_ID = "work-2222222222222222"
RELEASE = "paper-eval-v1"
GOLD_VERSION = "paper-gold-v1"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _empty_revision() -> dict[str, Any]:
    return {
        "question_type": None,
        "question": None,
        "answer": None,
        "acceptable_answers": [],
        "evidence": {
            "page_number": None,
            "text": None,
            "block_ids": [],
            "bbox": None,
            "bbox_normalized_top_left": None,
        },
    }


def _revision() -> dict[str, Any]:
    return {
        "question_type": "abstract_evidence",
        "question": "Which passage is the corrected evidence?",
        "answer": "The corrected extractive evidence.",
        "acceptable_answers": [],
        "evidence": {
            "page_number": None,
            "text": "The corrected extractive evidence.",
            "block_ids": ["p1-b2"],
            "bbox": None,
            "bbox_normalized_top_left": None,
        },
    }


def _question(question_id: str, text: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "question_id": question_id,
        "paper_id": PAPER_ID,
        "work_id": WORK_ID,
        "question_type": "abstract_evidence",
        "question": "Which passage states the contribution?",
        "answer": text,
        "evidence": {
            "page_number": 1,
            "bbox": [10.0, 20.0, 110.0, 40.0],
            "bbox_normalized_top_left": [0.05, 0.2, 0.55, 0.4],
            "text": text,
            "block_ids": ["p1-b1"],
        },
        "label_quality": "silver_extractive",
        "review_status": "machine_generated_pending_human_review",
    }


def _review_round(decision: str) -> dict[str, Any]:
    checks = {
        "question_clear": True,
        "answer_correct": True,
        "answer_unique": True,
        "evidence_supports_answer": True,
        "page_correct": True,
        "layout_location_correct": True,
    }
    issues: list[str] = []
    revision = _empty_revision()
    notes = None
    if decision == "edit":
        checks["answer_correct"] = False
        issues = ["WRONG_ANSWER"]
        revision = _revision()
        notes = "A bounded extractive correction is available."
    elif decision == "reject":
        checks["answer_correct"] = False
        issues = ["NOT_APPLICABLE"]
        notes = "This question type does not apply."
    return {
        "reviewer_alias": "reviewer-a",
        "decision": decision,
        "checks": checks,
        "issue_codes": issues,
        "proposed_revision": revision,
        "confidence": "high",
        "notes": notes,
        "reviewed_at_utc": "2026-08-01T00:00:00Z",
    }


def _review(question_id: str, decision: str) -> dict[str, Any]:
    first = _review_round(decision)
    second = copy.deepcopy(first)
    second["reviewed_at_utc"] = "2026-08-02T00:00:00Z"
    final_revision = _revision() if decision == "edit" else _empty_revision()
    return {
        "schema_version": "1.0.0",
        "annotation_spec_version": "1.0",
        "annotation_record_id": _annotation_id(RELEASE, question_id),
        "record_status": "resolved",
        "source": {
            "dataset_release": RELEASE,
            "question_id": question_id,
            "paper_id": PAPER_ID,
            "work_id": WORK_ID,
            "questions_silver_file_sha256": None,
            "source_checksums_file_sha256": None,
        },
        "review_protocol": "single_reviewer_interval_recheck",
        "reviews": {"round_1": first, "round_2": second},
        "resolution": {
            "status": "not_required",
            "resolver_alias": None,
            "final_decision": decision,
            "final_payload_source": {
                "keep": "silver",
                "edit": "final_revision",
                "reject": "none",
            }[decision],
            "issue_codes": [] if decision == "keep" else first["issue_codes"],
            "final_revision": final_revision,
            "rationale": None,
            "resolved_at_utc": "2026-08-02T00:00:00Z",
        },
        "gold_export": {
            "eligible": False,
            "gold_question_id": None,
            "label_quality": None,
            "review_status": None,
            "derivation": None,
        },
    }


def _prepare_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "dataset"
    workspace = tmp_path / "workspace"
    questions = [
        _question("eval-0000000000000001", "The original extractive evidence."),
        _question("eval-0000000000000002", "The original extractive evidence."),
        _question("eval-0000000000000003", "The original extractive evidence."),
    ]
    questions_path = dataset / "evaluation/questions.silver.jsonl"
    _write_jsonl(questions_path, questions)
    document_path = dataset / f"documents/{PAPER_ID}.json"
    _write_json(
        document_path,
        {
            "paper_id": PAPER_ID,
            "work_id": WORK_ID,
            "pages": [
                {
                    "page_number": 1,
                    "width": 200.0,
                    "height": 100.0,
                    "text_blocks": [
                        {
                            "block_id": "p1-b1",
                            "text": "The original extractive evidence.",
                            "bbox": [10.0, 20.0, 110.0, 40.0],
                            "reading_order": 0,
                        },
                        {
                            "block_id": "p1-b2",
                            "text": "The corrected extractive evidence.",
                            "bbox": [20.0, 50.0, 180.0, 70.0],
                            "reading_order": 1,
                        },
                    ],
                }
            ],
        },
    )
    checksum_rows = []
    for path in (questions_path, document_path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum_rows.append(f"{digest}  {path.relative_to(dataset).as_posix()}")
    checksums_path = workspace / "frozen/source_checksums.sha256"
    checksums_path.parent.mkdir(parents=True, exist_ok=True)
    checksums_path.write_text("\n".join(checksum_rows) + "\n", encoding="utf-8")
    silver_sha = hashlib.sha256(questions_path.read_bytes()).hexdigest()
    checksums_sha = hashlib.sha256(checksums_path.read_bytes()).hexdigest()
    _write_json(
        workspace / "frozen/input-manifest.json",
        {
            "schema_version": "1.0.0",
            "dataset_release": RELEASE,
            "questions_silver_file_sha256": silver_sha,
            "source_checksums_file_sha256": checksums_sha,
        },
    )
    for question, decision in zip(
        questions, ("keep", "edit", "reject"), strict=True
    ):
        review = _review(question["question_id"], decision)
        review["source"]["questions_silver_file_sha256"] = silver_sha
        review["source"]["source_checksums_file_sha256"] = checksums_sha
        _write_json(
            workspace
            / "reviews/records"
            / f"{review['annotation_record_id']}.json",
            review,
        )
    (workspace / "gold").mkdir(parents=True)
    return dataset, workspace


def test_build_gold_release_exports_keep_edit_and_reject(tmp_path: Path) -> None:
    dataset, workspace = _prepare_fixture(tmp_path)

    summary = build_gold_release(
        dataset,
        workspace,
        SCHEMAS,
        gold_version=GOLD_VERSION,
    )

    assert summary["review_count"] == 3
    assert summary["decision_counts"] == {"edit": 1, "keep": 1, "reject": 1}
    assert summary["gold_question_count"] == 2
    gold_rows = [
        json.loads(line)
        for line in (workspace / "gold/questions.gold.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["derivation"] for row in gold_rows] == ["unchanged", "corrected"]
    corrected = gold_rows[1]
    assert corrected["gold_question_id"] == _gold_id(
        GOLD_VERSION, "eval-0000000000000002"
    )
    assert corrected["evidence"] == {
        "page_number": 1,
        "text": "The corrected extractive evidence.",
        "block_ids": ["p1-b2"],
        "bbox": [20.0, 50.0, 180.0, 70.0],
        "bbox_normalized_top_left": [0.1, 0.5, 0.9, 0.7],
    }
    exported_reviews = [
        json.loads(line)
        for line in (workspace / "reviews/questions.review.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert exported_reviews[0]["gold_export"]["eligible"] is True
    assert exported_reviews[2]["gold_export"]["eligible"] is False
    assert _read_manifest(workspace)["status"] == "built"


def _read_manifest(workspace: Path) -> dict[str, Any]:
    return json.loads((workspace / "build_manifest.json").read_text(encoding="utf-8"))


def test_build_gold_release_rejects_changed_frozen_source(tmp_path: Path) -> None:
    dataset, workspace = _prepare_fixture(tmp_path)
    document_path = dataset / f"documents/{PAPER_ID}.json"
    document_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frozen source changed"):
        build_gold_release(
            dataset,
            workspace,
            SCHEMAS,
            gold_version=GOLD_VERSION,
        )


def test_build_gold_release_requires_used_document_in_frozen_list(
    tmp_path: Path,
) -> None:
    dataset, workspace = _prepare_fixture(tmp_path)
    checksums_path = workspace / "frozen/source_checksums.sha256"
    silver_line = next(
        line
        for line in checksums_path.read_text(encoding="utf-8").splitlines()
        if line.endswith("evaluation/questions.silver.jsonl")
    )
    checksums_path.write_text(silver_line + "\n", encoding="utf-8")
    checksums_sha = hashlib.sha256(checksums_path.read_bytes()).hexdigest()
    manifest_path = workspace / "frozen/input-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_checksums_file_sha256"] = checksums_sha
    _write_json(manifest_path, manifest)
    for review_path in (workspace / "reviews/records").glob("*.json"):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["source"]["source_checksums_file_sha256"] = checksums_sha
        _write_json(review_path, review)

    with pytest.raises(ValueError, match="parsed document is not frozen"):
        build_gold_release(
            dataset,
            workspace,
            SCHEMAS,
            gold_version=GOLD_VERSION,
        )


def test_build_gold_release_enforces_24_hour_recheck(tmp_path: Path) -> None:
    dataset, workspace = _prepare_fixture(tmp_path)
    review_path = next((workspace / "reviews/records").glob("*.json"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviews"]["round_2"]["reviewed_at_utc"] = "2026-08-01T23:59:59Z"
    review["resolution"]["resolved_at_utc"] = "2026-08-01T23:59:59Z"
    _write_json(review_path, review)

    with pytest.raises(ValueError, match="must wait 24 hours"):
        build_gold_release(
            dataset,
            workspace,
            SCHEMAS,
            gold_version=GOLD_VERSION,
        )


def test_build_gold_release_rejects_non_extractive_edit(tmp_path: Path) -> None:
    dataset, workspace = _prepare_fixture(tmp_path)
    edit_path = next(
        path
        for path in (workspace / "reviews/records").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["resolution"][
            "final_decision"
        ]
        == "edit"
    )
    review = json.loads(edit_path.read_text(encoding="utf-8"))
    for revision in (
        review["reviews"]["round_1"]["proposed_revision"],
        review["reviews"]["round_2"]["proposed_revision"],
        review["resolution"]["final_revision"],
    ):
        revision["evidence"]["text"] = "A fluent but unsupported answer."
        revision["answer"] = "A fluent but unsupported answer."
    _write_json(edit_path, review)

    with pytest.raises(ValueError, match="evidence text does not match"):
        build_gold_release(
            dataset,
            workspace,
            SCHEMAS,
            gold_version=GOLD_VERSION,
        )


def test_build_gold_release_refuses_unrequested_overwrite(tmp_path: Path) -> None:
    dataset, workspace = _prepare_fixture(tmp_path)
    build_gold_release(dataset, workspace, SCHEMAS, gold_version=GOLD_VERSION)

    with pytest.raises(FileExistsError, match="--replace-generated"):
        build_gold_release(dataset, workspace, SCHEMAS, gold_version=GOLD_VERSION)

    summary = build_gold_release(
        dataset,
        workspace,
        SCHEMAS,
        gold_version=GOLD_VERSION,
        replace_generated=True,
    )
    assert summary["gold_question_count"] == 2
