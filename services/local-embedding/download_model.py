#!/usr/bin/env python3
"""Download the project embedding model through ModelScope."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
from pathlib import Path

from modelscope import snapshot_download

DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_OUTPUT = Path(
    "/mnt/d/ScholarMindLocalLLM/models/Qwen3-Embedding-0.6B-modelscope"
)


def parse_args() -> argparse.Namespace:
    """Parse explicit model and output overrides."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """Download once and keep all model weights outside Git."""
    args = parse_args()
    output = args.output.expanduser().resolve()
    if (output / "config.json").is_file():
        print(f"Embedding model already exists: {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(args.model, local_dir=str(output))
    if not (output / "config.json").is_file():
        raise RuntimeError(f"download completed without config.json: {output}")
    print(f"Embedding model ready: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
