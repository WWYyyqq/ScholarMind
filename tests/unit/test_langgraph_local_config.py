"""Tests for the authentication-free local LangGraph configuration."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_local_config_loads_the_deep_researcher_without_auth() -> None:
    config = json.loads((ROOT / "langgraph.local.json").read_text())

    assert config["python_version"] == "3.11"
    assert config["env"] == "./.env"
    assert config["graphs"] == {
        "Deep Researcher": (
            "./src/open_deep_research/deep_researcher.py:deep_researcher"
        ),
        "ScholarMind Researcher": (
            "./src/scholarmind/graph.py:scholarmind_researcher"
        ),
    }
    assert "auth" not in config


def test_deployment_config_keeps_authentication() -> None:
    config = json.loads((ROOT / "langgraph.json").read_text())

    assert config["auth"]["path"] == "./src/security/auth.py:auth"
    assert config["graphs"]["ScholarMind Researcher"] == (
        "./src/scholarmind/graph.py:scholarmind_researcher"
    )
