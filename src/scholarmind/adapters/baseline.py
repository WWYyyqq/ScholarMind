"""Narrow compatibility adapter for the imported baseline's source payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..models import Evidence, EvidenceLocator, Source, SourceKind


class BaselineEvidenceAdapter:
    """Convert legacy search payloads without treating generated reports as evidence."""

    @staticmethod
    def sources_from_run(record: Mapping[str, Any]) -> tuple[Source, ...]:
        """Create URL sources from a baseline-run record's source_urls field."""
        source_urls = record.get("source_urls", ())
        if not isinstance(source_urls, Iterable) or isinstance(source_urls, str):
            raise ValueError("source_urls must be a sequence")
        sources: dict[str, Source] = {}
        for raw_url in source_urls:
            url = str(raw_url).strip()
            if not url:
                continue
            source = Source.create(
                kind=SourceKind.WEB,
                title=url,
                uri=url,
                identity=url,
                metadata={
                    "baseline_run_id": record.get("run_id"),
                    "baseline_record_id": record.get("record_id"),
                },
            )
            sources[source.source_id] = source
        return tuple(sources.values())

    @staticmethod
    def from_search_result(
        result: Mapping[str, Any], *, query: str | None = None
    ) -> tuple[Source, Evidence]:
        """Create source/evidence from a raw tool result that contains actual text."""
        url = str(result.get("url") or result.get("source") or "").strip()
        if not url:
            raise ValueError("search result requires url or source")
        text = str(
            result.get("raw_content")
            or result.get("content")
            or result.get("snippet")
            or ""
        ).strip()
        if not text:
            raise ValueError("search result requires raw_content, content, or snippet")
        source = Source.create(
            kind=SourceKind.WEB,
            title=str(result.get("title") or url),
            uri=url,
            identity=url,
            metadata={"query": query} if query else {},
        )
        evidence = Evidence.create(
            source_id=source.source_id,
            text=text,
            locator=EvidenceLocator(section="web-search-result"),
            metadata={"query": query, "score": result.get("score")},
        )
        return source, evidence
