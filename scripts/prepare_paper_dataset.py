#!/usr/bin/env python3
"""Build a non-destructive, evidence-aware paper dataset from local PDFs."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import statistics
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pymupdf

SCHEMA_VERSION = "1.0.0"
TRANSLATION_MARKERS = (
    "翻译结果",
    "【翻译】",
    "（翻译）",
    "(翻译结果)",
    "中文翻译",
    "翻译",
)
TITLE_KEY_ALIASES = {
    "deephunt": "interpretablefailurelocalizationformicroservicesystems",
    "uacadunsupervisedadversarialcontrastivelearningforanomalydetectiononmultimodaldatainmi": "uacadunsupervisedadversarialcontrastivelearningforanomalydetectiononmultimodaldatainmicroservicesystems",
    "atransformerbaseddeepneuralnetworkwithwavelettransformforforecastingwindspeedandwinde": "atransformerbaseddeepneuralnetworkwithwavelettransformforforecastingwindspeedandwindenergy",
}
GENERIC_PDF_TITLES = {
    "",
    "untitled",
    "microsoft word",
    "document",
    "main",
    "paper",
}
METHOD_HEADING_MARKERS = (
    "method",
    "approach",
    "framework",
    "model",
    "methodology",
    "architecture",
    "proposed",
    "方法",
    "框架",
    "模型",
)
INTRO_HEADING_MARKERS = ("introduction", "background", "引言", "介绍")
ABSTRACT_PATTERN = re.compile(
    r"(?is)(?:^|\n)\s*(?:abstract|摘要)\s*[:.：-]?\s*(.*?)"
    r"(?=\n\s*(?:keywords?|index terms|关键词)\b|"
    r"\n\s*(?:[1i]\.?\s*)?(?:introduction|引言)\b)"
)
HEADING_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)*|[IVX]+)\s*[.、:]?\s*\S+", re.IGNORECASE
)
SENTENCE_PATTERN = re.compile(r"(?s)^(.{60,700}?[.!?。！？])(?:\s|$)")


def utc_now() -> str:
    """Return the current UTC timestamp in RFC 3339 form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """Hash one file without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, value: str, length: int = 16) -> str:
    """Create a deterministic, non-secret identifier."""
    value_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"scholarmind:{prefix}:{value}")
    return f"{prefix}-{value_uuid.hex[:length]}"


def is_translation_name(name: str) -> bool:
    """Return whether a filename explicitly marks a translated copy."""
    return any(marker in name for marker in TRANSLATION_MARKERS)


def normalized_title_key(name: str) -> str:
    """Normalize a filename for original/translation and version grouping."""
    stem = Path(name).stem.lower()
    for marker in TRANSLATION_MARKERS:
        stem = stem.replace(marker.lower(), "")
    stem = re.sub(r"^\s*[（(]?ccf\s*[abc][）)]?\s*", "", stem)
    stem = re.sub(r"^有代码", "", stem)
    key = re.sub(r"[^a-z0-9一-鿿]+", "", stem)
    return TITLE_KEY_ALIASES.get(key, key)


def clean_filename_title(name: str) -> str:
    """Create a readable fallback title from a PDF filename."""
    title = Path(name).stem
    for marker in TRANSLATION_MARKERS:
        title = title.replace(marker, "")
    title = re.sub(r"^\s*[（(]?CCF\s*[ABC][）)]?\s*", "", title, flags=re.I)
    title = re.sub(r"^有代码", "", title)
    title = title.replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip(" -_.")
    return title


def classify_category(relative_path: Path, title: str) -> str:
    """Assign a deterministic coarse research category."""
    path_text = "/".join(relative_path.parts).lower()
    title_text = title.lower()
    if "综述" in path_text or "survey" in title_text or "review" in title_text:
        return "survey"
    if "llm" in path_text or "language model" in title_text or "logllm" in title_text:
        return "llm_for_aiops"
    if "mamba" in path_text:
        return "sequence_modeling"
    if "svdd" in path_text or "one-class" in title_text:
        return "one_class_anomaly_detection"
    if "小波" in path_text or "wavelet" in title_text:
        return "wavelet_time_series"
    if "动态图" in path_text or "dynamic graph" in title_text:
        return "dynamic_graph"
    root_markers = (
        "root cause",
        "failure localization",
        "fault localization",
        "troubleshooting",
        "causal",
        "causality",
        "根因",
        "故障定位",
    )
    if any(marker in title_text or marker in path_text for marker in root_markers):
        return "microservice_root_cause_analysis"
    if "anomaly" in title_text or "异常" in title_text:
        return "anomaly_detection"
    return "microservice_observability"


def infer_year(first_page_text: str) -> int | None:
    """Infer a publication year only from explicit front-page date cues."""
    cue_patterns = (
        r"(?:©|copyright)[ ]*(20[0-9]{2})",
        r"(?:accepted|published|publication)[^0-9]{0,24}(20[0-9]{2})",
        r"arxiv:[^ ]+.*?(20[0-9]{2})",
    )
    lowered = first_page_text.lower()
    for pattern in cue_patterns:
        match = re.search(pattern, lowered, re.IGNORECASE | re.DOTALL)
        if match:
            year = int(match.group(1))
            if 1990 <= year <= 2026:
                return year
    return None


def detect_language(text: str, translation_hint: bool) -> str:
    """Detect English or Chinese using a conservative CJK ratio."""
    sample = re.sub(r"\s+", "", text[:20000])
    if not sample:
        return "zh" if translation_hint else "unknown"
    cjk = sum("\u4e00" <= char <= "\u9fff" for char in sample)
    return "zh" if translation_hint or cjk / len(sample) >= 0.05 else "en"


def plausible_metadata_title(value: str | None) -> bool:
    """Reject empty and application-generated PDF title metadata."""
    if not value:
        return False
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) < 8 or len(normalized) > 400:
        return False
    lowered = normalized.lower()
    return not any(
        lowered == generic or lowered.startswith(generic + " ")
        for generic in GENERIC_PDF_TITLES
    )


def span_lines(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Collect text lines and typography from one page."""
    lines: list[dict[str, Any]] = []
    payload = page.get_text("dict", sort=True)
    for block_index, block in enumerate(payload.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if not text:
                continue
            sizes = [float(span.get("size", 0.0)) for span in spans]
            lines.append(
                {
                    "text": text,
                    "bbox": [
                        round(float(value), 2)
                        for value in line.get("bbox", block.get("bbox", (0, 0, 0, 0)))
                    ],
                    "max_font_size": round(max(sizes, default=0.0), 2),
                    "block_index": block_index,
                }
            )
    return lines


def extract_page_title(page: pymupdf.Page, fallback: str) -> str:
    """Extract a likely title from the strongest first-page typography cluster."""
    lines = span_lines(page)
    if not lines:
        return fallback
    page_height = float(page.rect.height)
    candidates = [
        line
        for line in lines
        if line["bbox"][1] <= page_height * 0.42
        and 2 <= len(line["text"]) <= 300
        and "@" not in line["text"]
        and not line["text"]
        .lower()
        .startswith(
            ("arxiv:", "abstract", "摘要", "contents lists", "journal homepage")
        )
    ]
    if not candidates:
        return fallback
    largest = max(line["max_font_size"] for line in candidates)
    prominent = [line for line in candidates if line["max_font_size"] >= largest * 0.90]
    prominent.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
    clusters: list[list[dict[str, Any]]] = []
    for line in prominent:
        if (
            not clusters
            or float(line["bbox"][1]) - float(clusters[-1][-1]["bbox"][3])
            > largest * 1.8
        ):
            clusters.append([line])
        else:
            clusters[-1].append(line)
    cluster = max(
        clusters,
        key=lambda group: (
            sum(len(str(line["text"])) for line in group),
            sum(float(line["max_font_size"]) for line in group),
            -float(group[0]["bbox"][1]),
        ),
    )
    title = " ".join(str(line["text"]) for line in cluster)
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) < 8 or len(title) > 240:
        return fallback
    return title


@dataclass
class SourceInspection:
    """Metadata collected from one source file before de-duplication."""

    path: Path
    relative_path: Path
    sha256: str
    byte_size: int
    pages: int
    title: str
    first_page_text: str
    language: str
    year: int | None
    category: str
    document_type: str
    normalized_title: str


def inspect_pdf(path: Path, source_root: Path) -> SourceInspection:
    """Read one PDF without modifying it and collect stable metadata."""
    relative_path = path.relative_to(source_root)
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError(
                f"file does not start with PDF magic bytes: {relative_path}"
            )
    digest = sha256_file(path)
    doc = pymupdf.open(path)
    if doc.needs_pass:
        doc.close()
        raise ValueError(f"encrypted PDF requires a password: {relative_path}")
    if len(doc) < 1:
        doc.close()
        raise ValueError(f"PDF has no pages: {relative_path}")
    sample_text = "\n".join(
        doc[index].get_text("text") for index in range(min(3, len(doc)))
    )
    first_page_text = doc[0].get_text("text", sort=True)
    fallback = clean_filename_title(path.name)
    page_title = extract_page_title(doc[0], "")
    metadata_title = (doc.metadata or {}).get("title")
    if plausible_metadata_title(page_title):
        title = page_title
    elif plausible_metadata_title(metadata_title):
        title = str(metadata_title).strip()
    else:
        title = fallback
    title = re.sub(r"\s+", " ", title).strip()
    translation = is_translation_name(path.name)
    inspection = SourceInspection(
        path=path,
        relative_path=relative_path,
        sha256=digest,
        byte_size=path.stat().st_size,
        pages=len(doc),
        title=title or fallback,
        first_page_text=first_page_text,
        language=detect_language(sample_text, translation),
        year=infer_year(first_page_text),
        category=classify_category(relative_path, title or fallback),
        document_type="translation" if translation else "original",
        normalized_title=normalized_title_key(path.name),
    )
    doc.close()
    return inspection


def canonical_preference(item: SourceInspection) -> tuple[int, int, str]:
    """Prefer dated research folders over baseline copies deterministically."""
    parts = {part.lower() for part in item.relative_path.parts}
    baseline_penalty = int(bool(parts & {"baseline", "baseline2"}))
    return (
        baseline_penalty,
        len(item.relative_path.parts),
        item.relative_path.as_posix(),
    )


def build_manifest(inspections: list[SourceInspection]) -> list[dict[str, Any]]:
    """Build file records with exact and logical work-level de-duplication."""
    by_hash: dict[str, list[SourceInspection]] = defaultdict(list)
    for item in inspections:
        by_hash[item.sha256].append(item)
    canonical_by_hash = {
        digest: sorted(group, key=canonical_preference)[0]
        for digest, group in by_hash.items()
    }
    record_by_path: dict[Path, dict[str, Any]] = {}
    for item in sorted(inspections, key=lambda value: value.relative_path.as_posix()):
        canonical = canonical_by_hash[item.sha256]
        file_id = stable_id("file", item.relative_path.as_posix())
        canonical_file_id = stable_id("file", canonical.relative_path.as_posix())
        record_by_path[item.relative_path] = {
            "schema_version": SCHEMA_VERSION,
            "file_id": file_id,
            "paper_id": f"paper-{item.sha256[:16]}",
            "work_id": None,
            "relative_path": item.relative_path.as_posix(),
            "filename": item.path.name,
            "sha256": item.sha256,
            "byte_size": item.byte_size,
            "pages": item.pages,
            "title": item.title,
            "normalized_title": item.normalized_title,
            "language": item.language,
            "document_type": item.document_type,
            "year": item.year,
            "category": item.category,
            "study_type": "survey" if item.category == "survey" else "research",
            "collection_tags": list(item.relative_path.parts[:-1]),
            "has_code_hint": item.path.name.startswith("有代码"),
            "is_exact_duplicate": item.relative_path != canonical.relative_path,
            "duplicate_of_file_id": (
                canonical_file_id
                if item.relative_path != canonical.relative_path
                else None
            ),
            "canonical_relative_path": canonical.relative_path.as_posix(),
            "translation_of_paper_id": None,
            "semantic_duplicate_of_paper_id": None,
            "index_policy": "pending",
            "indexable": False,
            "parser_status": "pending",
        }

    canonical_records = [
        record for record in record_by_path.values() if not record["is_exact_duplicate"]
    ]
    work_id_by_title: dict[str, str] = {}
    for record in canonical_records:
        key = str(record["normalized_title"]) or str(record["sha256"])
        work_id_by_title.setdefault(key, stable_id("work", key))
        record["work_id"] = work_id_by_title[key]
    work_id_by_hash = {
        str(record["sha256"]): str(record["work_id"]) for record in canonical_records
    }
    for record in record_by_path.values():
        if record["is_exact_duplicate"]:
            record["work_id"] = work_id_by_hash[str(record["sha256"])]

    def preference(record: dict[str, Any]) -> tuple[int, int, str]:
        relative_path = str(record["relative_path"])
        parts = {part.lower() for part in relative_path.split("/")}
        baseline_penalty = int(bool(parts & {"baseline", "baseline2"}))
        return baseline_penalty, relative_path.count("/"), relative_path

    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in canonical_records:
        by_work[str(record["work_id"])].append(record)
    for group in by_work.values():
        originals = sorted(
            (record for record in group if record["document_type"] == "original"),
            key=preference,
        )
        translations = sorted(
            (record for record in group if record["document_type"] == "translation"),
            key=preference,
        )
        if originals:
            primary = originals[0]
            primary["index_policy"] = "primary"
            primary["indexable"] = True
            for variant in originals[1:]:
                variant["index_policy"] = "skip_semantic_variant"
                variant["semantic_duplicate_of_paper_id"] = primary["paper_id"]
            for index, translation in enumerate(translations):
                translation["translation_of_paper_id"] = primary["paper_id"]
                if index == 0:
                    translation["index_policy"] = "auxiliary_translation"
                    translation["indexable"] = True
                else:
                    translation["index_policy"] = "skip_semantic_variant"
                    translation["semantic_duplicate_of_paper_id"] = translations[0][
                        "paper_id"
                    ]
        elif translations:
            primary = translations[0]
            primary["index_policy"] = "primary_translation_only"
            primary["indexable"] = True
            for variant in translations[1:]:
                variant["index_policy"] = "skip_semantic_variant"
                variant["semantic_duplicate_of_paper_id"] = primary["paper_id"]

    canonical_by_hash_record = {
        str(record["sha256"]): record for record in canonical_records
    }
    for record in record_by_path.values():
        if record["is_exact_duplicate"]:
            canonical = canonical_by_hash_record[str(record["sha256"])]
            record["translation_of_paper_id"] = canonical["translation_of_paper_id"]
            record["semantic_duplicate_of_paper_id"] = canonical[
                "semantic_duplicate_of_paper_id"
            ]
            record["index_policy"] = "skip_exact_duplicate"
            record["indexable"] = False
    return list(record_by_path.values())


def block_column(bbox: list[float], page_width: float) -> str:
    """Classify a text block as full-width, left-column, or right-column."""
    x0, _, x1, _ = bbox
    width = x1 - x0
    center = page_width / 2
    if width >= page_width * 0.68 or (
        x0 < center - page_width * 0.08 and x1 > center + page_width * 0.08
    ):
        return "full"
    if x1 <= center + page_width * 0.08:
        return "left"
    if x0 >= center - page_width * 0.08:
        return "right"
    return "full"


def page_blocks(
    page: pymupdf.Page,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract text and image geometry without embedding binary image payloads."""
    payload = page.get_text("dict", sort=True)
    text_blocks: list[dict[str, Any]] = []
    image_blocks: list[dict[str, Any]] = []
    for source_index, block in enumerate(payload.get("blocks", [])):
        bbox = [round(float(value), 2) for value in block.get("bbox", (0, 0, 0, 0))]
        if block.get("type") == 1:
            image_blocks.append(
                {
                    "source_index": source_index,
                    "bbox": bbox,
                    "width": int(block.get("width", 0)),
                    "height": int(block.get("height", 0)),
                }
            )
            continue
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        line_texts: list[str] = []
        sizes: list[float] = []
        fonts: set[str] = set()
        bold = False
        for line in lines:
            spans = line.get("spans", [])
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if text:
                line_texts.append(text)
            for span in spans:
                sizes.append(float(span.get("size", 0.0)))
                font = str(span.get("font", ""))
                if font:
                    fonts.add(font)
                bold = (
                    bold
                    or "bold" in font.lower()
                    or bool(int(span.get("flags", 0)) & 16)
                )
        text = "\n".join(line_texts).strip()
        if not text:
            continue
        text_blocks.append(
            {
                "source_index": source_index,
                "bbox": bbox,
                "column": block_column(bbox, float(page.rect.width)),
                "text": text,
                "max_font_size": round(max(sizes, default=0.0), 2),
                "median_font_size": round(statistics.median(sizes), 2)
                if sizes
                else 0.0,
                "fonts": sorted(fonts),
                "bold": bold,
            }
        )
    for order, block in enumerate(text_blocks):
        block["reading_order"] = order
    return text_blocks, image_blocks


def repeated_margin_texts(pages: list[dict[str, Any]]) -> set[str]:
    """Find short headers and footers repeated across many pages."""
    counts: Counter[str] = Counter()
    for page in pages:
        height = float(page["height"])
        seen: set[str] = set()
        for block in page["text_blocks"]:
            y0, y1 = float(block["bbox"][1]), float(block["bbox"][3])
            text = re.sub(r"\s+", " ", str(block["text"])).strip()
            normalized = re.sub(r"\d+", "#", text.lower())
            if len(text) <= 180 and (y1 <= height * 0.09 or y0 >= height * 0.91):
                seen.add(normalized)
        counts.update(seen)
    threshold = max(3, round(len(pages) * 0.3))
    return {text for text, count in counts.items() if count >= threshold}


def is_heading(block: dict[str, Any], body_font_size: float) -> bool:
    """Detect likely section headings from typography and numbering."""
    text = re.sub(r"\s+", " ", str(block["text"])).strip()
    if not text or len(text) > 180 or "\n" in text and len(text.splitlines()) > 3:
        return False
    typography = float(block["max_font_size"]) >= body_font_size * 1.17
    return HEADING_PATTERN.match(text) is not None or (
        bool(block["bold"]) and typography
    )


def union_bbox(bboxes: Iterable[list[float]]) -> list[float]:
    """Return one bounding box enclosing all provided boxes."""
    values = list(bboxes)
    if not values:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(min(box[0] for box in values), 2),
        round(min(box[1] for box in values), 2),
        round(max(box[2] for box in values), 2),
        round(max(box[3] for box in values), 2),
    ]


def normalized_bbox(
    document: dict[str, Any], page_number: int, bbox: list[float]
) -> list[float]:
    """Normalize one PDF-space bounding box to a top-left 0-to-1 coordinate space."""
    page = document["pages"][page_number - 1]
    width = max(float(page["width"]), 1.0)
    height = max(float(page["height"]), 1.0)
    return [
        round(max(0.0, min(1.0, bbox[0] / width)), 6),
        round(max(0.0, min(1.0, bbox[1] / height)), 6),
        round(max(0.0, min(1.0, bbox[2] / width)), 6),
        round(max(0.0, min(1.0, bbox[3] / height)), 6),
    ]


def split_text_for_chunks(text: str, max_chars: int) -> list[str]:
    """Split one oversized layout block near sentence or whitespace boundaries."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    remaining = text.strip()
    parts: list[str] = []
    minimum_break = max(1, int(max_chars * 0.55))
    boundary_pattern = re.compile(r"\n|[.!?。！？；;]\s*|\s+")
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        candidates = [
            match.end()
            for match in boundary_pattern.finditer(window)
            if minimum_break <= match.end() <= max_chars
        ]
        cut = max(candidates, default=max_chars)
        part = remaining[:cut].strip()
        if not part:
            cut = max_chars
            part = remaining[:cut]
        parts.append(part)
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def make_chunks(
    paper_id: str,
    work_id: str,
    title: str,
    language: str,
    category: str,
    indexable: bool,
    index_policy: str,
    pages: list[dict[str, Any]],
    max_chars: int,
) -> list[dict[str, Any]]:
    """Group adjacent blocks within one page and section into traceable chunks."""
    chunks: list[dict[str, Any]] = []
    for page in pages:
        current_section = "document"
        pending: list[dict[str, Any]] = []
        pending_chars = 0

        def flush() -> None:
            nonlocal pending, pending_chars
            if not pending:
                return
            text = "\n\n".join(str(block["text"]) for block in pending).strip()
            if text:
                ordinal = len(chunks)
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                chunks.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "chunk_id": stable_id(
                            "chunk",
                            f"{paper_id}:{page['page_number']}:{ordinal}:{content_hash}",
                        ),
                        "paper_id": paper_id,
                        "work_id": work_id,
                        "title": title,
                        "language": language,
                        "category": category,
                        "indexable": indexable,
                        "index_policy": index_policy,
                        "page_number": page["page_number"],
                        "section": current_section,
                        "text": text,
                        "char_count": len(text),
                        "token_estimate": max(1, round(len(text) / 4)),
                        "bbox": union_bbox([block["bbox"] for block in pending]),
                        "block_ids": [block["block_id"] for block in pending],
                        "block_orders": [block["reading_order"] for block in pending],
                        "content_sha256": content_hash,
                    }
                )
            pending = []
            pending_chars = 0

        for block in page["text_blocks"]:
            if block.get("is_repeated_margin"):
                continue
            if block.get("is_heading"):
                flush()
                current_section = re.sub(r"\s+", " ", str(block["text"])).strip()
                for fragment_text in split_text_for_chunks(
                    str(block["text"]), max_chars
                ):
                    if pending:
                        flush()
                    fragment = dict(block)
                    fragment["text"] = fragment_text
                    pending = [fragment]
                    pending_chars = len(fragment_text)
                continue
            for fragment_text in split_text_for_chunks(str(block["text"]), max_chars):
                fragment = dict(block)
                fragment["text"] = fragment_text
                fragment_chars = len(fragment_text)
                separator_chars = 2 if pending else 0
                if (
                    pending
                    and pending_chars + separator_chars + fragment_chars > max_chars
                ):
                    flush()
                    separator_chars = 0
                pending.append(fragment)
                pending_chars += separator_chars + fragment_chars
        flush()
    return chunks


def parse_document(
    path: Path,
    record: dict[str, Any],
    aliases: list[str],
    max_chars: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse one canonical PDF into page blocks, geometry, and chunks."""
    doc = pymupdf.open(path)
    pages: list[dict[str, Any]] = []
    font_sizes: list[float] = []
    for page_index, page in enumerate(doc):
        text_blocks, image_blocks = page_blocks(page)
        page_width = max(float(page.rect.width), 1.0)
        page_height = max(float(page.rect.height), 1.0)
        for block in text_blocks:
            block["block_id"] = f"p{page_index + 1}-b{int(block['source_index'])}"
            bbox = block["bbox"]
            block["bbox_normalized_top_left"] = [
                round(max(0.0, min(1.0, float(bbox[0]) / page_width)), 6),
                round(max(0.0, min(1.0, float(bbox[1]) / page_height)), 6),
                round(max(0.0, min(1.0, float(bbox[2]) / page_width)), 6),
                round(max(0.0, min(1.0, float(bbox[3]) / page_height)), 6),
            ]
        for image in image_blocks:
            image["block_id"] = f"p{page_index + 1}-i{int(image['source_index'])}"
        font_sizes.extend(
            float(block["median_font_size"])
            for block in text_blocks
            if float(block["median_font_size"]) > 0
        )
        pages.append(
            {
                "page_number": page_index + 1,
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "rotation": int(page.rotation),
                "text_blocks": text_blocks,
                "image_blocks": image_blocks,
                "text_char_count": sum(
                    len(str(block["text"])) for block in text_blocks
                ),
            }
        )
    doc.close()
    total_text_chars = sum(int(page["text_char_count"]) for page in pages)
    if total_text_chars < 200:
        raise ValueError(
            f"PDF needs OCR or contains too little extractable text: {path.name}"
        )
    body_font_size = statistics.median(font_sizes) if font_sizes else 10.0
    margins = repeated_margin_texts(pages)
    for page in pages:
        height = float(page["height"])
        for block in page["text_blocks"]:
            text = re.sub(r"\s+", " ", str(block["text"])).strip()
            normalized = re.sub(r"\d+", "#", text.lower())
            y0, y1 = float(block["bbox"][1]), float(block["bbox"][3])
            marginal = y1 <= height * 0.09 or y0 >= height * 0.91
            block["is_repeated_margin"] = marginal and normalized in margins
            block["is_heading"] = is_heading(block, body_font_size)
    chunks = make_chunks(
        str(record["paper_id"]),
        str(record["work_id"]),
        str(record["title"]),
        str(record["language"]),
        str(record["category"]),
        bool(record["indexable"]),
        str(record["index_policy"]),
        pages,
        max_chars,
    )
    for index, chunk in enumerate(chunks):
        page = pages[int(chunk["page_number"]) - 1]
        bbox = chunk["bbox"]
        chunk["bbox_normalized_top_left"] = [
            round(max(0.0, min(1.0, float(bbox[0]) / float(page["width"]))), 6),
            round(max(0.0, min(1.0, float(bbox[1]) / float(page["height"]))), 6),
            round(max(0.0, min(1.0, float(bbox[2]) / float(page["width"]))), 6),
            round(max(0.0, min(1.0, float(bbox[3]) / float(page["height"]))), 6),
        ]
        chunk["previous_chunk_id"] = chunks[index - 1]["chunk_id"] if index else None
        chunk["next_chunk_id"] = (
            chunks[index + 1]["chunk_id"] if index + 1 < len(chunks) else None
        )
    document = {
        "schema_version": SCHEMA_VERSION,
        "paper_id": record["paper_id"],
        "work_id": record["work_id"],
        "sha256": record["sha256"],
        "title": record["title"],
        "language": record["language"],
        "document_type": record["document_type"],
        "translation_of_paper_id": record["translation_of_paper_id"],
        "category": record["category"],
        "indexable": record["indexable"],
        "index_policy": record["index_policy"],
        "year": record["year"],
        "pages_count": len(pages),
        "coordinate_space": "pdf_points_top_left",
        "body_font_size": round(body_font_size, 2),
        "source_aliases": aliases,
        "parser": {
            "name": "pymupdf-layout-baseline",
            "version": pymupdf.version[0],
            "parsed_at": utc_now(),
            "max_chunk_chars": max_chars,
            "warnings": [
                "table structure and formulas are not semantically reconstructed"
            ],
        },
        "pages": pages,
        "chunk_count": len(chunks),
    }
    return document, chunks


def extract_abstract(
    document: dict[str, Any],
) -> tuple[str, int, list[float], list[str]] | None:
    """Extract an abstract span and the exact layout blocks supporting it."""
    for page in document["pages"][:2]:
        blocks = [
            block
            for block in page["text_blocks"]
            if not block.get("is_repeated_margin")
        ]
        parts: list[str] = []
        spans: list[tuple[int, int, dict[str, Any]]] = []
        cursor = 0
        for block in blocks:
            block_text = str(block["text"])
            start = cursor
            parts.append(block_text)
            cursor += len(block_text)
            spans.append((start, cursor, block))
            cursor += 1
        text = "\n".join(parts)
        match = ABSTRACT_PATTERN.search(text)
        if not match:
            continue
        abstract = re.sub(r"\s+", " ", match.group(1)).strip()
        if len(abstract) < 80:
            continue
        group_start, group_end = match.span(1)
        evidence_blocks = [
            block
            for start, end, block in spans
            if end > group_start and start < group_end
        ]
        if not evidence_blocks:
            continue
        return (
            abstract,
            int(page["page_number"]),
            union_bbox([block["bbox"] for block in evidence_blocks]),
            [str(block["block_id"]) for block in evidence_blocks],
        )
    return None


def first_sentence(text: str) -> str:
    """Return a bounded first full sentence or a safe extractive prefix."""
    normalized = re.sub(r"\s+", " ", text).strip()
    match = SENTENCE_PATTERN.match(normalized)
    if match:
        return match.group(1).strip()
    return normalized[:500].rstrip()


def first_method_heading(
    document: dict[str, Any],
) -> tuple[str, int, list[float], list[str]] | None:
    """Find the first heading likely to introduce a method or framework."""
    fallback: tuple[str, int, list[float], list[str]] | None = None
    for page in document["pages"]:
        for block in page["text_blocks"]:
            if not block.get("is_heading"):
                continue
            text = re.sub(r"\s+", " ", str(block["text"])).strip()
            lowered = text.lower()
            if fallback is None and any(
                marker in lowered for marker in INTRO_HEADING_MARKERS
            ):
                fallback = (
                    text,
                    int(page["page_number"]),
                    block["bbox"],
                    [str(block["block_id"])],
                )
            if any(marker in lowered for marker in METHOD_HEADING_MARKERS):
                return (
                    text,
                    int(page["page_number"]),
                    block["bbox"],
                    [str(block["block_id"])],
                )
    return fallback


def select_evaluation_records(
    canonical_records: list[dict[str, Any]], size: int
) -> list[dict[str, Any]]:
    """Select a deterministic category-balanced English-original holdout."""
    eligible: list[dict[str, Any]] = []
    seen_work_ids: set[str] = set()
    for record in canonical_records:
        work_id = str(record["work_id"])
        if (
            record["document_type"] == "original"
            and record["language"] == "en"
            and record["index_policy"] == "primary"
            and work_id not in seen_work_ids
        ):
            eligible.append(record)
            seen_work_ids.add(work_id)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in eligible:
        by_category[str(record["category"])].append(record)
    for group in by_category.values():
        group.sort(key=lambda item: (str(item["sha256"]), str(item["relative_path"])))
    selected: list[dict[str, Any]] = []
    categories = sorted(by_category)
    cursor = 0
    while len(selected) < min(size, len(eligible)):
        progressed = False
        for category in categories:
            group = by_category[category]
            if cursor < len(group):
                selected.append(group[cursor])
                progressed = True
                if len(selected) >= size:
                    break
        if not progressed:
            break
        cursor += 1
    return selected


def build_evaluation(
    selected: list[dict[str, Any]], documents: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a separate, extractive silver evaluation set with page evidence."""
    papers: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    for record in selected:
        paper_id = str(record["paper_id"])
        document = documents[paper_id]
        papers.append(
            {
                "schema_version": SCHEMA_VERSION,
                "paper_id": paper_id,
                "work_id": record["work_id"],
                "title": record["title"],
                "category": record["category"],
                "year": record["year"],
                "split": "test",
                "tuning_allowed": False,
                "selection": "deterministic_category_balanced",
            }
        )
        abstract = extract_abstract(document)
        if abstract:
            abstract_text, page_number, bbox, block_ids = abstract
            answer = first_sentence(abstract_text)
            questions.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "question_id": stable_id("eval", f"{paper_id}:abstract"),
                    "paper_id": paper_id,
                    "work_id": record["work_id"],
                    "question_type": "abstract_evidence",
                    "question": f"根据论文《{record['title']}》的摘要，作者如何概括研究问题或核心目标？请返回摘要中的原文证据。",
                    "answer": answer,
                    "evidence": {
                        "page_number": page_number,
                        "bbox": bbox,
                        "bbox_normalized_top_left": normalized_bbox(
                            document, page_number, bbox
                        ),
                        "text": answer,
                        "block_ids": block_ids,
                    },
                    "label_quality": "silver_extractive",
                    "review_status": "machine_generated_pending_human_review",
                }
            )
        heading = first_method_heading(document)
        if heading:
            heading_text, page_number, bbox, block_ids = heading
            questions.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "question_id": stable_id("eval", f"{paper_id}:method-heading"),
                    "paper_id": paper_id,
                    "work_id": record["work_id"],
                    "question_type": "method_section_locator",
                    "question": f"论文《{record['title']}》中首次用于介绍核心方法、框架或背景的相关章节标题是什么？",
                    "answer": heading_text,
                    "evidence": {
                        "page_number": page_number,
                        "bbox": bbox,
                        "bbox_normalized_top_left": normalized_bbox(
                            document, page_number, bbox
                        ),
                        "text": heading_text,
                        "block_ids": block_ids,
                    },
                    "label_quality": "silver_extractive",
                    "review_status": "machine_generated_pending_human_review",
                }
            )
    return papers, questions


def build_work_records(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize file and content records at the logical-paper level."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in manifest:
        grouped[str(record["work_id"])].append(record)
    works: list[dict[str, Any]] = []
    for work_id, group in sorted(grouped.items()):
        canonical = [record for record in group if not record["is_exact_duplicate"]]
        primary = next(
            (
                record
                for record in canonical
                if record["index_policy"] in {"primary", "primary_translation_only"}
            ),
            canonical[0],
        )
        works.append(
            {
                "schema_version": SCHEMA_VERSION,
                "work_id": work_id,
                "title": primary["title"],
                "category": primary["category"],
                "year": primary["year"],
                "primary_paper_id": primary["paper_id"],
                "source_file_count": len(group),
                "unique_content_count": len(
                    {str(record["paper_id"]) for record in canonical}
                ),
                "languages": sorted({str(record["language"]) for record in group}),
                "original_paper_ids": sorted(
                    {
                        str(record["paper_id"])
                        for record in canonical
                        if record["document_type"] == "original"
                    }
                ),
                "translation_paper_ids": sorted(
                    {
                        str(record["paper_id"])
                        for record in canonical
                        if record["document_type"] == "translation"
                    }
                ),
                "indexable_paper_ids": sorted(
                    {
                        str(record["paper_id"])
                        for record in canonical
                        if record["indexable"]
                    }
                ),
                "source_file_ids": sorted(str(record["file_id"]) for record in group),
                "dataset_split": primary.get("dataset_split"),
                "tuning_allowed": primary.get("tuning_allowed"),
            }
        )
    return works


def verify_source_unchanged(inspections: list[SourceInspection]) -> None:
    """Fail if any source PDF changed while the read-only build was running."""
    changes: list[str] = []
    for item in inspections:
        if not item.path.is_file():
            changes.append(f"{item.relative_path.as_posix()}: missing")
            continue
        if item.path.stat().st_size != item.byte_size:
            changes.append(f"{item.relative_path.as_posix()}: size changed")
            continue
        if sha256_file(item.path) != item.sha256:
            changes.append(f"{item.relative_path.as_posix()}: content changed")
    if changes:
        raise ValueError(f"source integrity check failed: {changes[:3]}")


def write_json(path: Path, payload: Any) -> None:
    """Write deterministic UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """Write UTF-8 JSON Lines with stable key order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def prepare_output(output: Path, replace: bool) -> tuple[Path, Path | None]:
    """Prepare an atomic build directory and preserve an existing output as backup."""
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if output.exists():
        if not replace:
            raise FileExistsError(
                f"output already exists: {output}; use --replace to preserve it as a backup"
            )
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = output.with_name(f"{output.name}.backup-{suffix}")
        if backup.exists():
            raise FileExistsError(f"backup target already exists: {backup}")
        output.rename(backup)
    build = output.with_name(f".{output.name}.build-{uuid.uuid4().hex[:8]}")
    build.mkdir(parents=False, exist_ok=False)
    return build, backup


def build_dataset(
    source_root: Path,
    output: Path,
    eval_size: int,
    max_chunk_chars: int,
    replace: bool,
) -> dict[str, Any]:
    """Build the complete local paper dataset and return its summary."""
    if (
        isinstance(max_chunk_chars, bool)
        or not isinstance(max_chunk_chars, int)
        or max_chunk_chars < 400
    ):
        raise ValueError("max_chunk_chars must be an integer of at least 400")
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"source directory does not exist: {source_root}")
    output = output.resolve()
    if (
        output == source_root
        or source_root in output.parents
        or output in source_root.parents
    ):
        raise ValueError("output directory must be outside source directory")
    source_files = sorted(
        (path for path in source_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )
    pdfs = [path for path in source_files if path.suffix.lower() == ".pdf"]
    ignored_non_pdf_count = len(source_files) - len(pdfs)
    if not pdfs:
        raise ValueError(f"no PDF files found under {source_root}")
    print(f"Inspecting {len(pdfs)} PDFs...")
    inspections: list[SourceInspection] = []
    failures: list[dict[str, str]] = []
    for index, path in enumerate(pdfs, start=1):
        try:
            inspections.append(inspect_pdf(path, source_root))
        except Exception as exc:
            failures.append(
                {
                    "relative_path": path.relative_to(source_root).as_posix(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"[{index}/{len(pdfs)}] inspected {path.name}")
    if failures:
        raise ValueError(f"{len(failures)} PDF files failed inspection: {failures[:3]}")

    manifest = build_manifest(inspections)
    by_relative = {item.relative_path.as_posix(): item for item in inspections}
    canonical_records = [
        record for record in manifest if not record["is_exact_duplicate"]
    ]
    aliases_by_paper: dict[str, list[str]] = defaultdict(list)
    for record in manifest:
        aliases_by_paper[str(record["paper_id"])].append(str(record["relative_path"]))

    build, backup = prepare_output(output, replace)
    documents: dict[str, dict[str, Any]] = {}
    all_chunks: list[dict[str, Any]] = []
    try:
        print(f"Parsing {len(canonical_records)} canonical PDFs...")
        for index, record in enumerate(canonical_records, start=1):
            inspection = by_relative[str(record["relative_path"])]
            document, chunks = parse_document(
                inspection.path,
                record,
                sorted(aliases_by_paper[str(record["paper_id"])]),
                max_chunk_chars,
            )
            documents[str(record["paper_id"])] = document
            all_chunks.extend(chunks)
            record["parser_status"] = "success"
            write_json(build / "documents" / f"{record['paper_id']}.json", document)
            print(
                f"[{index}/{len(canonical_records)}] parsed {record['relative_path']}"
            )
        status_by_hash = {
            str(record["sha256"]): record["parser_status"]
            for record in canonical_records
        }
        for record in manifest:
            record["parser_status"] = status_by_hash[str(record["sha256"])]

        selected = select_evaluation_records(canonical_records, eval_size)
        eval_papers, eval_questions = build_evaluation(selected, documents)
        selected_work_ids = {str(record["work_id"]) for record in selected}
        for record in canonical_records:
            in_test = str(record["work_id"]) in selected_work_ids
            record["dataset_split"] = "test" if in_test else "development"
            record["tuning_allowed"] = not in_test
        split_by_hash = {
            str(record["sha256"]): (record["dataset_split"], record["tuning_allowed"])
            for record in canonical_records
        }
        for record in manifest:
            split, allowed = split_by_hash[str(record["sha256"])]
            record["dataset_split"] = split
            record["tuning_allowed"] = allowed

        split_by_paper = {
            str(record["paper_id"]): (
                str(record["dataset_split"]),
                bool(record["tuning_allowed"]),
            )
            for record in canonical_records
        }
        for paper_id, document in documents.items():
            split, allowed = split_by_paper[paper_id]
            document["dataset_split"] = split
            document["tuning_allowed"] = allowed
            write_json(build / "documents" / f"{paper_id}.json", document)
        for chunk in all_chunks:
            split, allowed = split_by_paper[str(chunk["paper_id"])]
            chunk["dataset_split"] = split
            chunk["tuning_allowed"] = allowed
        development_chunks = [
            chunk
            for chunk in all_chunks
            if chunk["dataset_split"] == "development" and chunk["indexable"]
        ]
        evaluation_corpus_chunks = [
            chunk
            for chunk in all_chunks
            if chunk["dataset_split"] == "test" and chunk["indexable"]
        ]

        work_records = build_work_records(manifest)
        duplicate_groups = []
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in manifest:
            grouped[str(record["sha256"])].append(record)
        for digest, group in sorted(grouped.items()):
            if len(group) > 1:
                canonical = next(
                    record for record in group if not record["is_exact_duplicate"]
                )
                duplicate_groups.append(
                    {
                        "sha256": digest,
                        "paper_id": canonical["paper_id"],
                        "canonical_relative_path": canonical["relative_path"],
                        "aliases": sorted(
                            str(record["relative_path"]) for record in group
                        ),
                    }
                )

        write_jsonl(build / "manifest.jsonl", manifest)
        write_jsonl(build / "canonical_manifest.jsonl", canonical_records)
        write_jsonl(build / "works.jsonl", work_records)
        write_json(build / "duplicate_groups.json", duplicate_groups)
        write_jsonl(build / "chunks.jsonl", all_chunks)
        write_jsonl(build / "chunks.development.jsonl", development_chunks)
        write_jsonl(
            build / "evaluation" / "corpus.chunks.jsonl",
            evaluation_corpus_chunks,
        )
        write_jsonl(build / "evaluation" / "papers.jsonl", eval_papers)
        write_jsonl(build / "evaluation" / "questions.silver.jsonl", eval_questions)
        print("Verifying that source PDFs remained unchanged...")
        verify_source_unchanged(inspections)
        write_json(
            build / "dataset_config.json",
            {
                "schema_version": SCHEMA_VERSION,
                "source_root": "provided-at-runtime-and-not-serialized",
                "generated_at": utc_now(),
                "pdf_only": True,
                "source_files_copied": False,
                "source_integrity_verified": True,
                "source_pdf_count": len(pdfs),
                "ignored_non_pdf_count": ignored_non_pdf_count,
                "max_chunk_chars": max_chunk_chars,
                "evaluation_size_requested": eval_size,
            },
        )
        summary = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now(),
            "source_file_count": len(source_files),
            "source_pdf_count": len(pdfs),
            "ignored_non_pdf_count": ignored_non_pdf_count,
            "valid_pdf_count": len(inspections),
            "source_total_pages": sum(int(record["pages"]) for record in manifest),
            "canonical_pdf_count": len(canonical_records),
            "canonical_total_pages": sum(
                int(record["pages"]) for record in canonical_records
            ),
            "logical_work_count": len(work_records),
            "indexable_content_count": sum(
                bool(record["indexable"]) for record in canonical_records
            ),
            "semantic_variant_content_count": sum(
                record["index_policy"] == "skip_semantic_variant"
                for record in canonical_records
            ),
            "semantic_variant_work_count": len(
                {
                    str(record["work_id"])
                    for record in canonical_records
                    if record["index_policy"] == "skip_semantic_variant"
                }
            ),
            "exact_duplicate_file_count": len(manifest) - len(canonical_records),
            "exact_duplicate_group_count": len(duplicate_groups),
            "translation_file_count": sum(
                record["document_type"] == "translation" for record in manifest
            ),
            "canonical_translation_content_count": sum(
                record["document_type"] == "translation" for record in canonical_records
            ),
            "linked_translation_content_count": sum(
                bool(record["translation_of_paper_id"]) for record in canonical_records
            ),
            "linked_translation_work_count": len(
                {
                    str(record["work_id"])
                    for record in canonical_records
                    if record["translation_of_paper_id"]
                }
            ),
            "parsed_document_count": len(documents),
            "chunk_count": len(all_chunks),
            "development_chunk_count": len(development_chunks),
            "evaluation_corpus_chunk_count": len(evaluation_corpus_chunks),
            "indexable_chunk_count": sum(
                bool(chunk["indexable"]) for chunk in all_chunks
            ),
            "evaluation_paper_count": len(eval_papers),
            "evaluation_question_count": len(eval_questions),
            "evaluation_label_quality": "silver_extractive_pending_human_review",
            "source_integrity_verified": True,
            "category_counts": dict(
                sorted(
                    Counter(str(record["category"]) for record in work_records).items()
                )
            ),
            "language_counts": dict(
                sorted(
                    Counter(
                        str(record["language"]) for record in canonical_records
                    ).items()
                )
            ),
        }
        write_json(build / "summary.json", summary)
        (build / "README.md").write_text(
            "# ScholarMind Local Paper Dataset\n\n"
            "This directory is generated. Source PDFs remain read-only and are not "
            "copied here. No absolute source path is serialized.\n\n"
            f"- manifest.jsonl: {len(manifest)} source-PDF file records.\n"
            f"- canonical_manifest.jsonl: {len(canonical_records)} unique content records.\n"
            f"- works.jsonl: {len(work_records)} logical-paper records.\n"
            "- duplicate_groups.json: exact duplicate aliases; no source file was deleted.\n"
            "- documents/: page-, block-, typography-, image-, and bounding-box-aware JSON.\n"
            "- chunks.jsonl: page-bounded chunks carrying explicit index policy.\n"
            "- chunks.development.jsonl: indexable development-only chunks.\n"
            "- evaluation/corpus.chunks.jsonl: isolated test retrieval corpus.\n"
            "- evaluation/: a work-isolated silver test split with page evidence.\n\n"
            "Silver questions are deterministic extractive candidates and require human "
            "review before they can be called a gold benchmark.\n",
            encoding="utf-8",
        )
        build.rename(output.resolve())
        return summary
    except Exception:
        if build.exists():
            shutil.rmtree(build)
        if backup is not None and backup.exists() and not output.exists():
            backup.rename(output)
        raise


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Read-only directory recursively containing PDFs.",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New generated dataset directory."
    )
    parser.add_argument(
        "--eval-size",
        type=int,
        default=24,
        help="Number of canonical English originals held out for evaluation.",
    )
    parser.add_argument("--max-chunk-chars", type=int, default=1600)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Move an existing output to a timestamped backup before rebuilding.",
    )
    return parser.parse_args()


def main() -> int:
    """Build the dataset and print its final summary."""
    args = parse_args()
    if args.eval_size < 1:
        print("ERROR: --eval-size must be at least 1", file=sys.stderr)
        return 2
    if args.max_chunk_chars < 400:
        print("ERROR: --max-chunk-chars must be at least 400", file=sys.stderr)
        return 2
    try:
        summary = build_dataset(
            args.source,
            args.output,
            args.eval_size,
            args.max_chunk_chars,
            args.replace,
        )
    except (OSError, ValueError, pymupdf.FileDataError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
