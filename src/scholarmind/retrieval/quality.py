"""Explainable quality filtering for retrieved PDF evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Evidence
from ._text import tokenize
from .types import Retriever, SearchResult

_REFERENCE_SECTION_RE = re.compile(
    r"\b(?:references|bibliography|works cited)\b|参考文献",
    re.IGNORECASE,
)
_REFERENCE_ENTRY_RE = re.compile(
    r"^(?:\[\d{1,4}\]|\d{1,4}\.)\s+.{0,100}\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_REFERENCE_LIST_MARKER_RE = re.compile(r"(?:^|\s)\[\d{1,4}\]\s+(?=[A-Z])")
_RUNNING_HEADER_RE = re.compile(r"^\d+:\d+\s+")
_TERMINAL_PUNCTUATION_RE = re.compile(r"[.!?。！？][\"'”’)]?$")


@dataclass(frozen=True, slots=True)
class EvidenceQualityAssessment:
    """Explain whether one passage is suitable for retrieval and citation."""

    accepted: bool
    score: float
    reasons: tuple[str, ...] = ()


class EvidenceQualityPolicy:
    """Reject clear PDF debris and score softer quality signals."""

    def __init__(
        self,
        *,
        minimum_characters: int = 48,
        minimum_score: float = 0.45,
    ) -> None:
        """Configure conservative hard and soft quality thresholds."""
        if minimum_characters < 1:
            raise ValueError("minimum_characters must be positive")
        if not 0 <= minimum_score <= 1:
            raise ValueError("minimum_score must be between zero and one")
        self.minimum_characters = minimum_characters
        self.minimum_score = minimum_score

    def assess(self, evidence: Evidence) -> EvidenceQualityAssessment:
        """Return a deterministic score and public-safe rejection reasons."""
        text = " ".join(evidence.text.split())
        section = " ".join((evidence.locator.section or "").split())
        tokens = tokenize(text)
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        hard_reasons: list[str] = []
        soft_reasons: list[str] = []
        score = 1.0

        if len(text) < self.minimum_characters:
            hard_reasons.append("too_short")
        if evidence.locator.page_number is None:
            hard_reasons.append("missing_page")
        if section and _REFERENCE_SECTION_RE.search(section):
            hard_reasons.append("reference_section")
        if _REFERENCE_ENTRY_RE.search(text[:240]):
            hard_reasons.append("reference_entry")
        # PDF chunks sometimes begin with the tail of the previous reference,
        # so an anchored single-entry check is not sufficient. Two numbered
        # entries in one passage are a conservative signal for bibliography
        # content and avoid rejecting ordinary in-text citations such as [12].
        if len(_REFERENCE_LIST_MARKER_RE.findall(text)) >= 2:
            hard_reasons.append("reference_list")

        has_terminal_punctuation = bool(_TERMINAL_PUNCTUATION_RE.search(text))
        if (
            len(text) < 120
            and len(tokens) < 14
            and cjk_count < 14
            and not has_terminal_punctuation
        ):
            hard_reasons.append("heading_only")

        readable_characters = sum(
            character.isalnum() or "\u4e00" <= character <= "\u9fff"
            for character in text
        )
        if text and readable_characters / len(text) < 0.35 and cjk_count < 14:
            hard_reasons.append("low_text_density")

        if not section:
            score -= 0.05
            soft_reasons.append("missing_section")
        elif _RUNNING_HEADER_RE.match(section):
            score -= 0.15
            soft_reasons.append("running_header_section")
        if len(text) < 160:
            score -= 0.15
            soft_reasons.append("short_passage")
        if not has_terminal_punctuation:
            score -= 0.10
            soft_reasons.append("no_terminal_sentence")
        if len(set(tokens)) < 8 and cjk_count < 14:
            score -= 0.15
            soft_reasons.append("low_token_diversity")

        score = max(0.0, min(1.0, score))
        reasons = tuple(dict.fromkeys([*hard_reasons, *soft_reasons]))
        accepted = not hard_reasons and score >= self.minimum_score
        return EvidenceQualityAssessment(
            accepted=accepted,
            score=score,
            reasons=reasons,
        )


class QualityFilteredRetriever:
    """Over-fetch results and remove passages that are unsafe to cite."""

    def __init__(
        self,
        retriever: Retriever,
        *,
        policy: EvidenceQualityPolicy | None = None,
        candidate_multiplier: int = 3,
    ) -> None:
        """Configure the wrapped retriever and over-fetch budget."""
        if candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be positive")
        self.retriever = retriever
        self.policy = policy or EvidenceQualityPolicy()
        self.candidate_multiplier = candidate_multiplier

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Return accepted candidates while preserving component diagnostics."""
        if limit < 1:
            raise ValueError("limit must be positive")
        if not query.strip():
            return []
        candidates = self.retriever.search(
            query,
            limit=limit * self.candidate_multiplier,
        )
        accepted: list[SearchResult] = []
        for candidate in candidates:
            assessment = self.policy.assess(candidate.evidence)
            if not assessment.accepted:
                continue
            accepted.append(
                candidate.model_copy(
                    update={
                        "rank": len(accepted) + 1,
                        "quality_score": assessment.score,
                    }
                )
            )
            if len(accepted) >= limit:
                break
        return accepted
