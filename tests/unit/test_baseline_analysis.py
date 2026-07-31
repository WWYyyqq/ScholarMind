from scripts.analyze_baseline import latest_by_case, percentage


def test_latest_by_case_uses_highest_attempt():
    records = [
        {"case_id": "baseline-001", "attempt": 2, "value": "new"},
        {"case_id": "baseline-002", "attempt": 1, "value": "only"},
        {"case_id": "baseline-001", "attempt": 1, "value": "old"},
    ]

    latest = latest_by_case(records)

    assert latest["baseline-001"]["value"] == "new"
    assert latest["baseline-002"]["value"] == "only"


def test_percentage_is_rounded_and_zero_safe():
    assert percentage(1, 3) == 33.33
    assert percentage(0, 0) == 0.0
