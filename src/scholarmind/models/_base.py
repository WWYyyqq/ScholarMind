"""Shared behavior for immutable ScholarMind domain models."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize insignificant whitespace without changing letter case."""
    return _WHITESPACE.sub(" ", value).strip()


def _canonicalize(value: Any) -> Any:
    """Convert values to a deterministic JSON-compatible representation."""
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, set | frozenset):
        return sorted((_canonicalize(item) for item in value), key=repr)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_canonicalize(item) for item in value]
    return value


def stable_id(prefix: str, *identity_parts: Any, length: int = 20) -> str:
    """Return a deterministic public identifier for canonical identity parts."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError("ID prefix must contain lowercase letters, digits, or underscores")
    if not identity_parts:
        raise ValueError("at least one identity part is required")
    payload = json.dumps(
        _canonicalize(identity_parts),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:length]}"


class DomainModel(BaseModel):
    """Immutable base with stable JSON serialization semantics."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize as JSON-compatible data while retaining explicit nulls."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize deterministically for storage, logs, and API responses."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            separators=None if indent is not None else (",", ":"),
            sort_keys=True,
        )
