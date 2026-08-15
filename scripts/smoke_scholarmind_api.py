#!/usr/bin/env python3
"""Run a privacy-safe end-to-end smoke test against ScholarMind LangGraph."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any

DEFAULT_QUESTION = (
    "How do causal dependency graphs help localize root causes after anomalies "
    "in multivariate time series?"
)


def _request(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with opener.open(request, timeout=180) as response:
        body = json.loads(response.read().decode())
    if not isinstance(body, dict):
        raise RuntimeError("API returned a non-object JSON response")
    return body


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate publication gates and return a content-free summary."""
    if result.get("status") != "success":
        raise RuntimeError("research run did not return success")
    if result.get("publication_ready") is not True:
        raise RuntimeError("research run is not publication-ready")
    if not isinstance(result.get("report"), str) or not result["report"].strip():
        raise RuntimeError("research run returned no report")
    if result.get("errors") != []:
        raise RuntimeError("research run returned processing errors")

    evidence = result.get("evidence")
    claims = result.get("claims")
    citations = result.get("citations")
    if not isinstance(evidence, list) or not evidence:
        raise RuntimeError("research run returned an empty evidence chain")
    if not isinstance(claims, list) or not claims:
        raise RuntimeError("research run returned an empty evidence chain")
    if not isinstance(citations, list) or not citations:
        raise RuntimeError("research run returned an empty evidence chain")

    evidence_ids = {
        item.get("evidence_id") for item in evidence if isinstance(item, dict)
    }
    claim_ids = {item.get("claim_id") for item in claims if isinstance(item, dict)}
    if None in evidence_ids or None in claim_ids:
        raise RuntimeError("research run returned malformed entity IDs")
    if any(
        not isinstance(item, dict)
        or item.get("evidence_id") not in evidence_ids
        or item.get("claim_id") not in claim_ids
        or not isinstance(item.get("locator"), dict)
        or item["locator"].get("page_number") is None
        for item in citations
    ):
        raise RuntimeError("citation chain is broken or lacks page locations")

    counts = result.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("research run returned no counts")
    expected = {
        "evidence": len(evidence),
        "claims": len(claims),
        "citations": len(citations),
    }
    if any(counts.get(key) != value for key, value in expected.items()):
        raise RuntimeError("research counts disagree with returned entities")

    return {
        "status": "passed",
        "publication_ready": True,
        "counts": counts,
        "report_characters": len(result["report"]),
        "citation_links_valid": True,
    }


def main() -> int:
    """Call the local graph and print only a privacy-safe validation summary."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:2024")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument(
        "--retrieval-mode",
        choices=("dense", "hybrid", "hybrid-rerank"),
        default="hybrid-rerank",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")

    base_url = args.base_url.rstrip("/")
    health = _request(f"{base_url}/ok")
    if health.get("ok") is not True:
        raise RuntimeError("LangGraph health endpoint is not ready")
    result = _request(
        f"{base_url}/runs/wait",
        {
            "assistant_id": "ScholarMind Researcher",
            "input": {
                "question": args.question,
                "retrieval_mode": args.retrieval_mode,
                "top_k": args.top_k,
            },
        },
    )
    print(json.dumps(validate_result(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
