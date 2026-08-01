"""Adapter for the PR5 manifest and page-bounded chunk contracts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..models import Evidence, EvidenceLocator, Source, SourceKind

if TYPE_CHECKING:
    from ..retrieval import EvidenceIndexer, IndexingResult
    from ..storage import EvidenceRepository, VectorEvidenceRepository


DatasetSplit = Literal["development", "test"]


class PaperDatasetRecordError(ValueError):
    """Raised when a manifest or chunk cannot be mapped without losing provenance."""


def _required(record: Mapping[str, Any], key: str) -> Any:
    """Return a non-null record value or raise a contextual adapter error."""
    value = record.get(key)
    if value is None or value == "":
        raise PaperDatasetRecordError(f"paper dataset record is missing {key!r}")
    return value


@dataclass(frozen=True)
class PaperDatasetBundle:
    """Domain entities produced from one manifest/chunk pair."""

    sources: tuple[Source, ...]
    evidence: tuple[Evidence, ...]
    dataset_split: DatasetSplit = "development"

    def ingest(self, repository: EvidenceRepository) -> None:
        """Insert sources before their dependent evidence records."""
        for source in self.sources:
            repository.upsert_source(source)
        for item in self.evidence:
            repository.upsert_evidence(item)

    def ingest_and_index(
        self,
        repository: VectorEvidenceRepository,
        indexer: EvidenceIndexer,
    ) -> IndexingResult:
        """Persist the bundle and batch-index its evidence embeddings."""
        self.ingest(repository)
        return indexer.index(self.evidence, repository)


class PaperDatasetAdapter:
    """Translate pipeline JSONL records into provenance-preserving models."""

    @staticmethod
    def source_from_manifest(record: Mapping[str, Any]) -> Source:
        """Map one canonical PR5 manifest record to a Source."""
        paper_id = str(_required(record, "paper_id"))
        relative_path = str(_required(record, "relative_path"))
        canonical_path = str(record.get("canonical_relative_path") or relative_path)
        aliases = tuple(
            dict.fromkeys(path for path in (canonical_path, relative_path) if path)
        )
        metadata_keys = (
            "schema_version",
            "file_id",
            "filename",
            "byte_size",
            "pages",
            "year",
            "category",
            "document_type",
            "study_type",
            "index_policy",
            "indexable",
            "dataset_split",
            "tuning_allowed",
            "translation_of_paper_id",
            "semantic_duplicate_of_paper_id",
        )
        return Source.create(
            kind=SourceKind.PAPER,
            title=str(_required(record, "title")),
            uri=canonical_path,
            content_sha256=str(_required(record, "sha256")),
            paper_id=paper_id,
            work_id=str(_required(record, "work_id")),
            language=str(record.get("language") or "unknown"),
            aliases=aliases,
            metadata={key: record.get(key) for key in metadata_keys if key in record},
            identity=paper_id,
        )

    @staticmethod
    def evidence_from_chunk(
        record: Mapping[str, Any], source: Source
    ) -> Evidence:
        """Map one page-bounded chunk while retaining every source locator."""
        paper_id = str(_required(record, "paper_id"))
        if paper_id != source.paper_id:
            raise PaperDatasetRecordError(
                f"chunk paper_id {paper_id!r} does not match source {source.paper_id!r}"
            )
        bbox_value = record.get("bbox")
        bbox: tuple[float, float, float, float] | None = None
        if bbox_value is not None:
            if not isinstance(bbox_value, list | tuple) or len(bbox_value) != 4:
                raise PaperDatasetRecordError("chunk bbox must contain four coordinates")
            bbox = tuple(float(value) for value in bbox_value)  # type: ignore[assignment]
        locator = EvidenceLocator(
            page_number=int(_required(record, "page_number")),
            section=str(record.get("section") or "unknown"),
            bbox=bbox,
            chunk_id=str(_required(record, "chunk_id")),
            block_ids=tuple(str(value) for value in record.get("block_ids", ())),
        )
        metadata_keys = (
            "schema_version",
            "work_id",
            "title",
            "language",
            "category",
            "indexable",
            "index_policy",
            "dataset_split",
            "tuning_allowed",
            "char_count",
            "token_estimate",
            "bbox_normalized_top_left",
            "block_orders",
            "previous_chunk_id",
            "next_chunk_id",
        )
        return Evidence.create(
            source_id=source.source_id,
            text=str(_required(record, "text")),
            locator=locator,
            content_sha256=str(_required(record, "content_sha256")),
            metadata={key: record.get(key) for key in metadata_keys if key in record},
            identity=locator.chunk_id,
        )

    @classmethod
    def from_records(
        cls,
        manifest_records: Iterable[Mapping[str, Any]],
        chunk_records: Iterable[Mapping[str, Any]],
        *,
        indexable_only: bool = True,
        dataset_split: DatasetSplit = "development",
    ) -> PaperDatasetBundle:
        """Build one split-isolated bundle from in-memory pipeline records."""
        if dataset_split not in {"development", "test"}:
            raise ValueError("dataset_split must be development or test")
        canonical_by_paper: dict[str, Mapping[str, Any]] = {}
        for record in manifest_records:
            if str(_required(record, "dataset_split")) != dataset_split:
                continue
            paper_id = str(_required(record, "paper_id"))
            current = canonical_by_paper.get(paper_id)
            if current is None or (
                bool(current.get("is_exact_duplicate"))
                and not bool(record.get("is_exact_duplicate"))
            ):
                canonical_by_paper[paper_id] = record

        sources_by_paper: dict[str, Source] = {}
        for paper_id, record in canonical_by_paper.items():
            if indexable_only and not bool(record.get("indexable", True)):
                continue
            sources_by_paper[paper_id] = cls.source_from_manifest(record)

        evidence_by_id: dict[str, Evidence] = {}
        for record in chunk_records:
            if str(_required(record, "dataset_split")) != dataset_split:
                continue
            if indexable_only and not bool(record.get("indexable", True)):
                continue
            paper_id = str(_required(record, "paper_id"))
            source = sources_by_paper.get(paper_id)
            if source is None:
                if paper_id not in canonical_by_paper:
                    raise PaperDatasetRecordError(
                        f"chunk references unknown paper_id {paper_id!r}"
                    )
                continue
            item = cls.evidence_from_chunk(record, source)
            previous = evidence_by_id.get(item.evidence_id)
            if previous is not None and previous != item:
                raise PaperDatasetRecordError(
                    f"conflicting chunks produce {item.evidence_id!r}"
                )
            evidence_by_id[item.evidence_id] = item

        return PaperDatasetBundle(
            sources=tuple(
                sorted(sources_by_paper.values(), key=lambda item: item.source_id)
            ),
            evidence=tuple(
                sorted(evidence_by_id.values(), key=lambda item: item.evidence_id)
            ),
            dataset_split=dataset_split,
        )

    @classmethod
    def load_jsonl(
        cls,
        manifest_path: str | Path,
        chunks_path: str | Path,
        *,
        indexable_only: bool = True,
        dataset_split: DatasetSplit = "development",
    ) -> PaperDatasetBundle:
        """Load one isolated split from pipeline manifest and chunk JSONL files."""

        def read_records(path: str | Path) -> list[dict[str, Any]]:
            records: list[dict[str, Any]] = []
            with Path(path).open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise PaperDatasetRecordError(
                            f"{path}:{line_number} must contain a JSON object"
                        )
                    records.append(value)
            return records

        return cls.from_records(
            read_records(manifest_path),
            read_records(chunks_path),
            indexable_only=indexable_only,
            dataset_split=dataset_split,
        )
