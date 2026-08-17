"""Deterministic first-pass verification for evidence-grounded claims.

The verifier is deliberately conservative.  It is not intended to replace an
NLI model or a human reviewer; it enforces the non-negotiable publication gate
and catches common numeric, polarity, and overstatement errors before a writer
can turn them into fluent prose.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from scholarmind.models import Claim, Evidence

_TOKEN_RE = re.compile(r"[a-zA-Z]+(?:[-'][a-zA-Z]+)*|\d+(?:\.\d+)?%?|[\u4e00-\u9fff]")
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:%|(?![\w.]))")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+")
_NEGATION_RE = re.compile(
    r"\b(?:no|not|never|neither|without|failed?|cannot|can't|didn't|doesn't|"
    r"isn't|wasn't|weren't)\b|(?:不|未|无|没有|并非|不能|失败)",
    re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
    "了",
    "为",
    "与",
    "和",
    "在",
    "是",
    "的",
}


class VerificationStatus(str, Enum):
    """Supportedness verdict used by the report publication gate."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Explainable result of checking one claim against its linked evidence."""

    status: VerificationStatus
    explanation: str
    evidence_ids: tuple[str, ...] = ()
    coverage: float = 0.0
    confidence: float = 0.0
    verification_method: str = "deterministic"
    hard_gate_passed: bool = True

    def __post_init__(self) -> None:
        """Keep invalid scores or unsupported citations out of API payloads."""
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("verification coverage must be between 0 and 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("verification confidence must be between 0 and 1")
        if self.status is VerificationStatus.SUPPORTED and not self.evidence_ids:
            raise ValueError("supported verification requires evidence IDs")
        if not self.verification_method.strip():
            raise ValueError("verification method must not be empty")

    @property
    def allows_publication(self) -> bool:
        """Return whether this claim may enter a factual report."""
        return self.status is VerificationStatus.SUPPORTED


class ClaimVerificationProvider(Protocol):
    """Verify one claim against only its explicitly linked evidence."""

    def verify(
        self,
        claim: Claim,
        evidence: Iterable[Evidence] | Mapping[str, Evidence],
    ) -> VerificationResult:
        """Return an explainable, fail-closed publication verdict."""


class ClaimVerifier:
    """Apply a conservative lexical/numeric verification policy.

    The class is deterministic so it can act as a reliable safety gate in local
    development and CI.  A semantic/NLI verifier can later be composed ahead of
    this gate, but it must not bypass the explicit evidence-link requirement.
    """

    def __init__(
        self,
        *,
        supported_threshold: float = 0.8,
        partial_threshold: float = 0.45,
    ) -> None:
        """Configure lexical coverage thresholds."""
        if not 0 <= partial_threshold <= supported_threshold <= 1:
            raise ValueError(
                "thresholds must satisfy 0 <= partial <= supported <= 1"
            )
        self.supported_threshold = supported_threshold
        self.partial_threshold = partial_threshold

    def verify(
        self,
        claim: Claim,
        evidence: Iterable[Evidence] | Mapping[str, Evidence],
    ) -> VerificationResult:
        """Verify a claim using only evidence IDs explicitly linked by the claim."""
        available = self._evidence_by_id(evidence)
        linked_ids = tuple(dict.fromkeys(claim.evidence_ids))
        if not linked_ids:
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT,
                explanation="Factual claim has no linked evidence.",
                hard_gate_passed=False,
            )

        unresolved_ids = tuple(
            evidence_id for evidence_id in linked_ids if evidence_id not in available
        )
        if unresolved_ids:
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT,
                explanation=(
                    "Claim references unavailable evidence ID(s): "
                    + ", ".join(unresolved_ids)
                ),
                hard_gate_passed=False,
            )

        linked = [available[evidence_id] for evidence_id in linked_ids]
        if not linked:
            return VerificationResult(
                status=VerificationStatus.INSUFFICIENT,
                explanation="None of the claim's evidence IDs resolves to available evidence.",
                hard_gate_passed=False,
            )

        evidence_text, supporting_evidence_id = _best_support_span(claim.text, linked)
        evidence_ids = (supporting_evidence_id,)
        claim_numbers = set(_NUMBER_RE.findall(claim.text))
        evidence_numbers = {
            number
            for item in linked
            for number in _NUMBER_RE.findall(item.text)
        }
        missing_numbers = claim_numbers - evidence_numbers
        claim_tokens = _content_tokens(claim.text)
        evidence_tokens = _content_tokens(evidence_text)
        coverage = _coverage(claim_tokens, evidence_tokens)

        if missing_numbers:
            conflicting_numbers = bool(evidence_numbers)
            status = (
                VerificationStatus.CONTRADICTED
                if conflicting_numbers
                else VerificationStatus.INSUFFICIENT
            )
            reason = "conflicts with" if conflicting_numbers else "is absent from"
            return VerificationResult(
                status=status,
                explanation=(
                    f"Claim number(s) {sorted(missing_numbers)} {reason} the linked "
                    "evidence."
                ),
                evidence_ids=evidence_ids,
                coverage=coverage,
                confidence=coverage,
                hard_gate_passed=False,
            )

        if coverage >= self.partial_threshold and _is_negated(
            claim.text
        ) != _is_negated(evidence_text):
            return VerificationResult(
                status=VerificationStatus.CONTRADICTED,
                explanation="Claim and linked evidence have conflicting polarity.",
                evidence_ids=evidence_ids,
                coverage=coverage,
                confidence=coverage,
                hard_gate_passed=False,
            )

        if coverage >= self.supported_threshold and _is_extractive_match(
            claim.text, evidence_text
        ):
            return VerificationResult(
                status=VerificationStatus.SUPPORTED,
                explanation=(
                    "Linked evidence covers the claim's material terms, numbers, "
                    "and polarity."
                ),
                evidence_ids=evidence_ids,
                coverage=coverage,
                confidence=coverage,
            )
        if coverage >= self.partial_threshold:
            return VerificationResult(
                status=VerificationStatus.PARTIAL,
                explanation=(
                    "Linked evidence has material lexical overlap, but the claim is "
                    "not a strict extractive match or is only partly covered."
                ),
                evidence_ids=evidence_ids,
                coverage=coverage,
                confidence=coverage,
            )
        return VerificationResult(
            status=VerificationStatus.INSUFFICIENT,
            explanation="Linked evidence does not cover enough material claim terms.",
            evidence_ids=evidence_ids,
            coverage=coverage,
            confidence=coverage,
        )

    @staticmethod
    def _evidence_by_id(
        evidence: Iterable[Evidence] | Mapping[str, Evidence],
    ) -> dict[str, Evidence]:
        if isinstance(evidence, Mapping):
            return dict(evidence)
        return {item.evidence_id: item for item in evidence}


def _content_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(text)
        if token.casefold() not in _STOPWORDS
    }


def _best_support_span(
    claim_text: str,
    evidence: Sequence[Evidence],
) -> tuple[str, str]:
    claim_tokens = _content_tokens(claim_text)
    spans = [
        (span, item.evidence_id)
        for item in evidence
        for span in _SENTENCE_BOUNDARY_RE.split(item.text)
        if span.strip()
    ]
    if not spans:  # Evidence text is model-validated, so this is defensive only.
        return "", evidence[0].evidence_id
    return max(
        spans,
        key=lambda pair: (
            _is_extractive_match(claim_text, pair[0]),
            _coverage(claim_tokens, _content_tokens(pair[0])),
            -len(pair[0]),
        ),
    )


def _coverage(claim_tokens: set[str], evidence_tokens: set[str]) -> float:
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & evidence_tokens) / len(claim_tokens)


def _is_extractive_match(claim_text: str, evidence_span: str) -> bool:
    normalized_claim = " ".join(claim_text.split()).casefold()
    normalized_evidence = " ".join(evidence_span.split()).casefold()
    return bool(normalized_claim) and normalized_claim in normalized_evidence


def _is_negated(text: str) -> bool:
    return _NEGATION_RE.search(text) is not None
