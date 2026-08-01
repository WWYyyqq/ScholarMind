"""Adapters at the boundary between legacy/data-pipeline records and the domain."""

from .baseline import BaselineEvidenceAdapter
from .paper_dataset import PaperDatasetAdapter, PaperDatasetBundle

__all__ = [
    "BaselineEvidenceAdapter",
    "PaperDatasetAdapter",
    "PaperDatasetBundle",
]
