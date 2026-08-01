"""Public ScholarMind domain model API."""

from ._base import DomainModel, normalize_text, stable_id
from .citation import Citation
from .claim import Claim, ClaimStatus
from .evidence import Evidence, EvidenceLocator
from .source import Source, SourceKind

__all__ = [
    "Citation",
    "Claim",
    "ClaimStatus",
    "DomainModel",
    "Evidence",
    "EvidenceLocator",
    "Source",
    "SourceKind",
    "normalize_text",
    "stable_id",
]
