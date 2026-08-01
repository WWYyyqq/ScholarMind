"""Dependency-free multilingual tokenization for local fallbacks."""

from __future__ import annotations

import re

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Tokenize Latin words and CJK unigrams/bigrams deterministically."""
    raw = [token.casefold() for token in _TOKEN_PATTERN.findall(text)]
    result = list(raw)
    cjk_run: list[str] = []

    def append_bigrams() -> None:
        if len(cjk_run) > 1:
            result.extend(
                cjk_run[index] + cjk_run[index + 1]
                for index in range(len(cjk_run) - 1)
            )
        cjk_run.clear()

    for token in raw:
        if len(token) == 1 and "\u4e00" <= token <= "\u9fff":
            cjk_run.append(token)
        else:
            append_bigrams()
    append_bigrams()
    return result
