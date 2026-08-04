#!/usr/bin/env python3
"""Smoke-test the local OpenAI-compatible embedding endpoint."""

# ruff: noqa: T201

from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request

BASE_URL = "http://[::1]:8001"
MODEL = "qwen3-embedding-0.6b-local"
EXPECTED_DIMENSION = 1024
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path: str, payload: dict | None = None) -> dict | str:
    """Call the local endpoint without inheriting proxy settings."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with OPENER.open(req, timeout=180) as response:
        body = response.read().decode()
        return json.loads(body) if body else ""


def cosine(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two non-empty vectors."""
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def main() -> int:
    """Verify health, model discovery, dimension, and semantic ordering."""
    try:
        request("/health")
        models = request("/v1/models")
        assert isinstance(models, dict)
        assert MODEL in {item["id"] for item in models["data"]}
        result = request(
            "/v1/embeddings",
            {
                "model": MODEL,
                "encoding_format": "float",
                "input": [
                    (
                        "Instruct: Given an academic research question, retrieve "
                        "relevant paper passages.\nQuery: 什么是图神经网络？"
                    ),
                    "图神经网络通过消息传递聚合邻居节点的信息。",
                    "卷积神经网络常用于处理规则网格上的图像。",
                ],
            },
        )
        assert isinstance(result, dict)
        vectors = [
            item["embedding"]
            for item in sorted(result["data"], key=lambda item: item["index"])
        ]
        assert len(vectors) == 3
        assert {len(vector) for vector in vectors} == {EXPECTED_DIMENSION}
        relevant = cosine(vectors[0], vectors[1])
        irrelevant = cosine(vectors[0], vectors[2])
        assert relevant > irrelevant
        print(
            "PASS local embeddings: "
            f"dimension={EXPECTED_DIMENSION}, relevant={relevant:.4f}, "
            f"irrelevant={irrelevant:.4f}"
        )
    except (
        AssertionError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
