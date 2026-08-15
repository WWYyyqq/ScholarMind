from __future__ import annotations

import pytest

from scripts.smoke_scholarmind_api import validate_result


def _result() -> dict[str, object]:
    return {
        "status": "success",
        "publication_ready": True,
        "report": "# Evidence report",
        "errors": [],
        "evidence": [{"evidence_id": "evidence-1"}],
        "claims": [{"claim_id": "claim-1"}],
        "citations": [
            {
                "claim_id": "claim-1",
                "evidence_id": "evidence-1",
                "locator": {"page_number": 3},
            }
        ],
        "counts": {
            "evidence": 1,
            "claims": 1,
            "published_claims": 1,
            "citations": 1,
        },
    }


def test_api_smoke_validates_complete_citation_chain() -> None:
    summary = validate_result(_result())

    assert summary["status"] == "passed"
    assert summary["citation_links_valid"] is True
    assert summary["report_characters"] > 0


def test_api_smoke_rejects_page_less_citation() -> None:
    result = _result()
    result["citations"] = [
        {
            "claim_id": "claim-1",
            "evidence_id": "evidence-1",
            "locator": {"page_number": None},
        }
    ]

    with pytest.raises(RuntimeError, match="citation chain"):
        validate_result(result)


def test_api_smoke_rejects_count_mismatch() -> None:
    result = _result()
    result["counts"] = {
        "evidence": 2,
        "claims": 1,
        "published_claims": 1,
        "citations": 1,
    }

    with pytest.raises(RuntimeError, match="counts disagree"):
        validate_result(result)
