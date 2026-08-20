#!/usr/bin/env python3
"""Freeze Silver inputs and create private, content-minimized review queues."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

QUESTION_TYPES = ("abstract_evidence", "method_section_locator")
EXPECTED_COUNTS = {"abstract_evidence": 19, "method_section_locator": 23}
REQUIRED_INPUTS = (
    "dataset_config.json",
    "canonical_manifest.jsonl",
    "evaluation/papers.jsonl",
    "evaluation/corpus.chunks.jsonl",
    "evaluation/questions.silver.jsonl",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a private Silver review workspace without changing the dataset."
        )
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--schemas", type=Path, default=Path("evaluation/schemas"))
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(
            "docs/evaluation/paper-dataset/templates/review-record.template.json"
        ),
    )
    parser.add_argument("--release", default="paper-eval-v1")
    parser.add_argument("--reviewer-alias", default="reviewer-a")
    parser.add_argument(
        "--protocol",
        choices=(
            "single_reviewer_interval_recheck",
            "independent_two_reviewer",
        ),
        default="single_reviewer_interval_recheck",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_questions(path: Path, schema_path: Path) -> tuple[dict[str, Any], ...]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"questions.silver.jsonl:{line_number}: blank line")
        record = json.loads(line)
        errors = sorted(validator.iter_errors(record), key=lambda item: list(item.path))
        if errors:
            raise ValueError(
                f"questions.silver.jsonl:{line_number}: {errors[0].message}"
            )
        question_id = record["question_id"]
        if question_id in seen:
            raise ValueError(f"duplicate question_id: {question_id}")
        seen.add(question_id)
        questions.append(record)
    counts = Counter(item["question_type"] for item in questions)
    if len(questions) != 42 or dict(counts) != EXPECTED_COUNTS:
        raise ValueError(
            "expected the frozen 42-question Silver release "
            f"(19 abstract, 23 method); got {len(questions)} and {dict(counts)}"
        )
    return tuple(questions)


def _batches(
    questions: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    by_type = {
        question_type: [
            item for item in questions if item["question_type"] == question_type
        ]
        for question_type in QUESTION_TYPES
    }
    targets = {
        "calibration": (2, 3),
        "round-1-a": (5, 7),
        "round-1-b": (6, 7),
        "round-1-c": (6, 6),
    }
    offsets = {question_type: 0 for question_type in QUESTION_TYPES}
    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for name, target in targets.items():
        selected: list[dict[str, Any]] = []
        for question_type, count in zip(QUESTION_TYPES, target, strict=True):
            start = offsets[question_type]
            selected.extend(by_type[question_type][start : start + count])
            offsets[question_type] += count
        result[name] = tuple(selected)
    return result


def _annotation_id(release: str, question_id: str) -> str:
    value = hashlib.sha256(f"{release}\0{question_id}".encode()).hexdigest()[:16]
    return f"annotation-{value}"


def _queue_record(
    question: dict[str, Any],
    *,
    release: str,
    batch: str,
) -> dict[str, Any]:
    return {
        "annotation_record_id": _annotation_id(release, question["question_id"]),
        "question_id": question["question_id"],
        "paper_id": question["paper_id"],
        "work_id": question["work_id"],
        "question_type": question["question_type"],
        "batch": batch,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


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


def main(argv: list[str] | None = None) -> int:
    """Create frozen checksums, skeleton records, and two blind review queues."""
    args = _parser().parse_args(argv)
    dataset = args.dataset.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", args.release):
        raise ValueError("release may contain only letters, digits, dot, dash, underscore")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", args.reviewer_alias):
        raise ValueError("reviewer alias contains unsafe characters")
    missing = [item for item in REQUIRED_INPUTS if not (dataset / item).is_file()]
    if missing:
        raise FileNotFoundError("missing dataset inputs: " + ", ".join(missing))
    documents = sorted((dataset / "documents").glob("paper-*.json"))
    if not documents:
        raise FileNotFoundError("dataset documents directory is empty")
    if output.exists():
        raise FileExistsError(
            "review output already exists; choose a new release directory"
        )

    questions_path = dataset / "evaluation/questions.silver.jsonl"
    questions = _read_questions(
        questions_path,
        args.schemas.expanduser().resolve() / "paper_eval_question.schema.json",
    )
    review_schema = json.loads(
        (
            args.schemas.expanduser().resolve() / "paper_review.schema.json"
        ).read_text(encoding="utf-8")
    )
    review_validator = Draft202012Validator(review_schema)
    template = json.loads(args.template.expanduser().resolve().read_text(encoding="utf-8"))
    batches = _batches(questions)
    batch_by_question = {
        item["question_id"]: batch
        for batch, items in batches.items()
        for item in items
    }

    frozen = output / "frozen-input"
    queue = output / "queue"
    records = output / "reviews/records"
    gold = output / "gold"
    for directory in (frozen, queue, records, gold):
        directory.mkdir(parents=True, exist_ok=False)

    checksum_paths = [dataset / item for item in REQUIRED_INPUTS]
    checksum_paths.extend(documents)
    checksum_lines = [
        f"{_sha256(path)}  {path.relative_to(dataset).as_posix()}"
        for path in checksum_paths
    ]
    checksum_file = frozen / "source_checksums.sha256"
    checksum_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    silver_sha = _sha256(questions_path)
    checksums_sha = _sha256(checksum_file)

    queue_rows = [
        _queue_record(
            item,
            release=args.release,
            batch=batch_by_question[item["question_id"]],
        )
        for item in questions
    ]
    _write_jsonl(queue / "round-1.queue.jsonl", queue_rows)
    _write_jsonl(queue / "round-2.queue.jsonl", list(reversed(queue_rows)))
    _write_jsonl(queue / "adjudication.queue.jsonl", [])
    for item in questions:
        record = copy.deepcopy(template)
        record.pop("template_notice", None)
        record["annotation_record_id"] = _annotation_id(
            args.release, item["question_id"]
        )
        record["source"] = {
            "dataset_release": args.release,
            "question_id": item["question_id"],
            "paper_id": item["paper_id"],
            "work_id": item["work_id"],
            "questions_silver_file_sha256": silver_sha,
            "source_checksums_file_sha256": checksums_sha,
        }
        record["review_protocol"] = args.protocol
        errors = list(review_validator.iter_errors(record))
        if errors:
            raise ValueError(
                "generated review record violates paper_review.schema.json: "
                f"{errors[0].message}"
            )
        _write_json(records / f"{record['annotation_record_id']}.json", record)

    now = datetime.now(UTC).isoformat()
    manifest = {
        "schema_version": "1.0.0",
        "dataset_release": args.release,
        "created_at_utc": now,
        "scholarmind_git_commit": _git_commit(),
        "annotation_spec_version": "1.0",
        "review_protocol": args.protocol,
        "reviewer_alias": args.reviewer_alias,
        "questions_silver_file_sha256": silver_sha,
        "source_checksums_file_sha256": checksums_sha,
        "question_count": len(questions),
        "question_type_counts": dict(Counter(item["question_type"] for item in questions)),
        "batches": {name: len(items) for name, items in batches.items()},
    }
    _write_json(frozen / "input-manifest.json", manifest)
    _write_json(output / "build_manifest.json", {**manifest, "status": "prepared"})
    (output / "review_summary.md").write_text(
        "# Silver review summary\n\n"
        f"- Release: `{args.release}`\n"
        f"- Prepared at: `{now}`\n"
        "- Status: prepared; no human decisions recorded yet\n"
        "- Silver questions: 42 (19 abstract, 23 method locator)\n"
        "- Gold questions: not built\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "question_count": len(questions),
                "record_count": len(list(records.glob("*.json"))),
                "source_checksums_file_sha256": checksums_sha,
                "content_policy": "queues contain IDs only; review records are empty",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
