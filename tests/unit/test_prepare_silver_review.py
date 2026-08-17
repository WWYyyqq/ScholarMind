"""Tests for deterministic, content-minimized Silver review batching."""

from scripts.prepare_silver_review import _annotation_id, _batches


def _questions() -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for index in range(19):
        rows.append(
            {
                "question_id": f"abstract-{index}",
                "question_type": "abstract_evidence",
            }
        )
    for index in range(23):
        rows.append(
            {
                "question_id": f"method-{index}",
                "question_type": "method_section_locator",
            }
        )
    return tuple(rows)


def test_review_batches_cover_every_question_once_with_planned_counts() -> None:
    batches = _batches(_questions())

    assert {name: len(rows) for name, rows in batches.items()} == {
        "calibration": 5,
        "round-1-a": 12,
        "round-1-b": 13,
        "round-1-c": 12,
    }
    question_ids = [
        item["question_id"] for rows in batches.values() for item in rows
    ]
    assert len(question_ids) == len(set(question_ids)) == 42


def test_annotation_ids_are_stable_and_release_scoped() -> None:
    first = _annotation_id("paper-eval-v1", "eval-0123456789abcdef")

    assert first == _annotation_id("paper-eval-v1", "eval-0123456789abcdef")
    assert first != _annotation_id("paper-eval-v2", "eval-0123456789abcdef")
    assert first.startswith("annotation-")
    assert len(first) == 27
