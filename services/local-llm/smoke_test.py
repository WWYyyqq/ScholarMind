#!/usr/bin/env python3
"""Smoke-test the local vLLM OpenAI-compatible endpoint."""

# ruff: noqa: T201

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://[::1]:8000"
MODEL = "qwen3-14b-local"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path: str, payload: dict | None = None) -> dict | str:
    """Call the local endpoint without inheriting system proxy settings."""
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


def main() -> int:
    """Run health, generation, structured-output, and tool-call checks."""
    try:
        request("/health")
        models = request("/v1/models")
        assert MODEL in {item["id"] for item in models["data"]}
        print("PASS health and model discovery")

        completion = request(
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": "只回答：API正常"}],
                "temperature": 0,
                "max_tokens": 128,
            },
        )
        content = completion["choices"][0]["message"]["content"]
        assert content
        print(f"PASS chat completion: {content.strip()[:80]}")

        structured = request(
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": "返回服务状态，status 必须是 ok，model 必须是 qwen3。",
                    }
                ],
                "temperature": 0,
                "max_tokens": 128,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "service_status",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "enum": ["ok"]},
                                "model": {"type": "string"},
                            },
                            "required": ["status", "model"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
        )
        value = json.loads(structured["choices"][0]["message"]["content"])
        assert value["status"] == "ok"
        print(f"PASS structured output: {value}")

        tool_call = request(
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": "请调用 get_paper 工具查询 arXiv:1706.03762。",
                    }
                ],
                "temperature": 0,
                "max_tokens": 256,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_paper",
                            "description": "按 arXiv ID 查询论文",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "arxiv_id": {"type": "string"},
                                },
                                "required": ["arxiv_id"],
                            },
                        },
                    }
                ],
                "tool_choice": "auto",
            },
        )
        calls = tool_call["choices"][0]["message"].get("tool_calls") or []
        assert calls and calls[0]["function"]["name"] == "get_paper"
        print(f"PASS tool call: {calls[0]['function']}")
    except (AssertionError, KeyError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
