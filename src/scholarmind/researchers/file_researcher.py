"""Evidence-first research over already ingested local document chunks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from scholarmind.models import Citation, Claim, ClaimStatus, Evidence, Source
from scholarmind.retrieval import Retriever, SearchResult
from scholarmind.verification import (
    ClaimVerifier,
    VerificationResult,
    VerificationStatus,
)

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]", re.IGNORECASE)
_REFERENCE_START_RE = re.compile(r"^\[\d{1,4}\]\s+")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_ROMAN_HEADING_RE = re.compile(r"^(?:[IVXLCDM]+\.|\d+(?:\.\d+)*\.?)$")
_AUTHOR_FRAGMENT_RE = re.compile(r'^[A-Z][A-Za-z-]{1,30},\s+["“]')
_CLAIM_TERMINAL_PUNCTUATION_RE = re.compile(r"[.!?。！？][\"'”’)]?$")
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "do",
        "does",
        "for",
        "how",
        "in",
        "is",
        "of",
        "the",
        "to",
        "what",
        "which",
        "with",
    }
)


class ResearchStatus(str, Enum):
    """Overall outcome of one local-file research request."""

    SUCCESS = "success"
    COMPLETE = "success"  # Backward-compatible alias.
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    """Unverified factual statement proposed from retrieved evidence."""

    text: str
    evidence_ids: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ClaimGenerator(Protocol):
    """Generate evidence-linked claim drafts without writing a report."""

    def generate(
        self,
        question: str,
        evidence: Sequence[Evidence],
    ) -> Sequence[ClaimDraft]:
        """Return candidate claims for later verification."""


class ExtractiveClaimGenerator:
    """Create deterministic smoke-test claims directly from evidence sentences."""

    def __init__(self, *, max_claims: int = 5) -> None:
        """Limit the number of extractive claims generated per request."""
        if max_claims < 1:
            raise ValueError("max_claims must be positive")
        self.max_claims = max_claims

    def generate(
        self,
        question: str,
        evidence: Sequence[Evidence],
    ) -> Sequence[ClaimDraft]:
        """Select a complete, question-relevant sentence from each passage."""
        drafts: list[ClaimDraft] = []
        for item in evidence:
            sentence = _best_sentence(item.text, question=question)
            if not sentence:
                continue
            drafts.append(
                ClaimDraft(
                    text=sentence,
                    evidence_ids=(item.evidence_id,),
                    metadata={
                        "claim_type": "fact",
                        "generator": "extractive-query-aware",
                    },
                )
            )
            if len(drafts) >= self.max_claims:
                break
        return drafts


@dataclass(frozen=True, slots=True)
class FileResearchResult:
    """Structured result that separates published and rejected factual claims."""

    question: str
    status: ResearchStatus
    evidence: tuple[Evidence, ...] = ()
    claims: tuple[Claim, ...] = ()
    verifications: tuple[VerificationResult, ...] = ()
    citations: tuple[Citation, ...] = ()
    report: str | None = None
    errors: tuple[str, ...] = ()

    @property
    def publication_ready(self) -> bool:
        """Return whether a non-empty, evidence-gated report is available."""
        return self.report is not None and bool(self.published_claims)

    @property
    def published_claims(self) -> tuple[Claim, ...]:
        """Return only claims that passed the strict support gate."""
        return tuple(
            claim for claim in self.claims if claim.status is ClaimStatus.SUPPORTED
        )

    @property
    def rejected_claims(self) -> tuple[Claim, ...]:
        """Return all claims kept out of the factual report."""
        return tuple(
            claim for claim in self.claims if claim.status is not ClaimStatus.SUPPORTED
        )

    @property
    def source_ids(self) -> tuple[str, ...]:
        """Return source IDs in first-seen retrieval order."""
        return tuple(dict.fromkeys(item.source_id for item in self.evidence))


class FileResearcher:
    """Retrieve local evidence, verify claims, and render page-level citations."""

    def __init__(
        self,
        retriever: Retriever,
        *,
        claim_generator: ClaimGenerator | None = None,
        verifier: ClaimVerifier | None = None,
        sources: Mapping[str, Source] | None = None,
        top_k: int = 5,
    ) -> None:
        """Configure the local retriever and evidence publication gate."""
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.retriever = retriever
        self.claim_generator = claim_generator or ExtractiveClaimGenerator()
        self.verifier = verifier or ClaimVerifier()
        self.sources = dict(sources or {})
        self.top_k = top_k

    def research(self, question: str) -> FileResearchResult:
        """Run the local evidence pipeline without using web search."""
        normalized_question = " ".join(question.split())
        if not normalized_question:
            raise ValueError("question must not be empty")

        try:
            hits = self.retriever.search(normalized_question, limit=self.top_k)
        except Exception as exc:  # A structured failure is safer than fake prose.
            return FileResearchResult(
                question=normalized_question,
                status=ResearchStatus.FAILED,
                errors=(f"Retrieval failed: {type(exc).__name__}: {exc}",),
            )

        try:
            evidence, hit_errors = _page_located_evidence(hits)
        except Exception as exc:
            return FileResearchResult(
                question=normalized_question,
                status=ResearchStatus.FAILED,
                errors=(
                    f"Retrieval result validation failed: {type(exc).__name__}: {exc}",
                ),
            )
        processing_errors = list(hit_errors)
        if not evidence:
            return FileResearchResult(
                question=normalized_question,
                status=ResearchStatus.FAILED,
                errors=tuple(
                    [*processing_errors, "No page-located local evidence was retrieved."]
                ),
            )

        try:
            drafts = tuple(
                self.claim_generator.generate(normalized_question, evidence)
            )
        except Exception as exc:
            return FileResearchResult(
                question=normalized_question,
                status=ResearchStatus.FAILED,
                evidence=evidence,
                errors=tuple(
                    [
                        *processing_errors,
                        f"Claim generation failed: {type(exc).__name__}: {exc}",
                    ]
                ),
            )
        if not drafts:
            return FileResearchResult(
                question=normalized_question,
                status=ResearchStatus.FAILED,
                evidence=evidence,
                errors=tuple(
                    [
                        *processing_errors,
                        "No evidence-linked claim drafts were generated.",
                    ]
                ),
            )

        evidence_by_id = {item.evidence_id: item for item in evidence}
        claims: list[Claim] = []
        verifications: list[VerificationResult] = []
        citations: list[Citation] = []
        for index, draft in enumerate(drafts, start=1):
            try:
                claim = Claim.create(
                    text=draft.text,
                    evidence_ids=draft.evidence_ids,
                    metadata=dict(draft.metadata),
                )
            except Exception as exc:
                processing_errors.append(
                    f"Claim draft {index} was rejected: {type(exc).__name__}: {exc}"
                )
                continue

            try:
                verification = self.verifier.verify(claim, evidence_by_id)
            except Exception as exc:
                message = f"Claim {claim.claim_id} verification failed: {type(exc).__name__}: {exc}"
                processing_errors.append(message)
                failure = _failed_verification(message)
                claims.append(_claim_with_failure(claim, failure))
                verifications.append(failure)
                continue

            try:
                verified_claim = _verified_claim(claim, verification)
            except Exception as exc:
                message = f"Claim {claim.claim_id} finalization failed: {type(exc).__name__}: {exc}"
                processing_errors.append(message)
                claims.append(claim)
                verifications.append(_failed_verification(message))
                continue

            if not verification.allows_publication:
                claims.append(verified_claim)
                verifications.append(verification)
                continue

            try:
                claim_citations = tuple(
                    Citation.create(
                        claim_id=verified_claim.claim_id,
                        evidence_id=item.evidence_id,
                        source_id=item.source_id,
                        locator=item.locator,
                        label=self._citation_label(item),
                    )
                    for evidence_id in verification.evidence_ids
                    for item in (evidence_by_id[evidence_id],)
                )
                if not claim_citations:
                    raise ValueError("supported claim produced no citations")
            except Exception as exc:
                message = f"Claim {claim.claim_id} citation failed: {type(exc).__name__}: {exc}"
                processing_errors.append(message)
                failure = _failed_verification(
                    message,
                    evidence_ids=verification.evidence_ids,
                    coverage=verification.coverage,
                )
                claims.append(_claim_with_failure(claim, failure))
                verifications.append(failure)
                continue

            claims.append(verified_claim)
            verifications.append(verification)
            citations.extend(claim_citations)

        published = [
            claim for claim in claims if claim.status is ClaimStatus.SUPPORTED
        ]
        if not published:
            return FileResearchResult(
                question=normalized_question,
                status=ResearchStatus.FAILED,
                evidence=evidence,
                claims=tuple(claims),
                verifications=tuple(verifications),
                errors=tuple(
                    [*processing_errors, "All candidate claims failed the evidence gate."]
                ),
            )

        status = (
            ResearchStatus.SUCCESS
            if not processing_errors
            and len(published) == len(claims) == len(drafts)
            else ResearchStatus.PARTIAL
        )
        return FileResearchResult(
            question=normalized_question,
            status=status,
            evidence=evidence,
            claims=tuple(claims),
            verifications=tuple(verifications),
            citations=tuple(citations),
            report=_render_report(normalized_question, published, citations),
            errors=tuple(processing_errors),
        )

    def _citation_label(self, evidence: Evidence) -> str:
        source = self.sources.get(evidence.source_id)
        source_label = source.title if source is not None else evidence.source_id
        page = evidence.locator.page_number
        page_end = evidence.locator.page_end
        page_label = f"pp. {page}-{page_end}" if page_end and page_end != page else f"p. {page}"
        return f"[{source_label}, {page_label}]"


def _first_sentence(text: str) -> str:
    """Return the first usable sentence for backward-compatible callers."""
    return _best_sentence(text, question="")


def _best_sentence(text: str, *, question: str) -> str:
    """Choose an informative exact sentence while rejecting PDF noise."""
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    candidates = [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY_RE.split(normalized)
        if _is_informative_sentence(sentence.strip())
    ]
    if not candidates:
        return ""

    query_terms = _terms(question) - _QUERY_STOPWORDS
    ranked = max(
        enumerate(candidates),
        key=lambda indexed: (
            _sentence_score(indexed[1], query_terms=query_terms),
            -indexed[0],
        ),
    )
    return ranked[1]


def _is_informative_sentence(sentence: str) -> bool:
    """Reject headings, bibliography entries, and short extraction debris."""
    if len(sentence) < 28 or _ROMAN_HEADING_RE.fullmatch(sentence):
        return False
    if not _CLAIM_TERMINAL_PUNCTUATION_RE.search(sentence):
        return False
    if sentence[0].isascii() and sentence[0].islower():
        return False
    if _REFERENCE_START_RE.match(sentence):
        return False
    if _YEAR_RE.search(sentence) and _AUTHOR_FRAGMENT_RE.match(sentence):
        return False

    lowered = sentence.casefold()
    reference_terms = (
        "proceedings of",
        "conference on",
        "transactions on",
        " et al.",
        " pp.",
    )
    if _YEAR_RE.search(sentence) and any(term in lowered for term in reference_terms):
        return False

    tokens = _terms(sentence)
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", sentence))
    return len(tokens) >= 5 or cjk_count >= 14


def _terms(text: str) -> set[str]:
    return {match.casefold() for match in _TOKEN_RE.findall(text)}


def _sentence_score(sentence: str, *, query_terms: set[str]) -> tuple[int, int, int]:
    terms = _terms(sentence)
    overlap = len(terms & query_terms)
    # Cap length so a malformed page cannot outrank a concise factual sentence
    # merely by containing more extraction noise.
    useful_length = min(len(sentence), 240)
    has_method_signal = int(
        bool(
            terms
            & {
                "approach",
                "detect",
                "detection",
                "method",
                "model",
                "results",
                "uses",
                "using",
            }
        )
    )
    return overlap, has_method_signal, useful_length


def _page_located_evidence(
    hits: Sequence[SearchResult],
) -> tuple[tuple[Evidence, ...], tuple[str, ...]]:
    unique: dict[str, Evidence] = {}
    errors: list[str] = []
    for index, hit in enumerate(hits, start=1):
        try:
            item = hit.evidence
            if not isinstance(item, Evidence):
                raise TypeError("search result evidence is not an Evidence model")
            if item.locator.page_number is None:
                continue
            unique.setdefault(item.evidence_id, item)
        except Exception as exc:
            errors.append(
                f"Search hit {index} was ignored: {type(exc).__name__}: {exc}"
            )
    return tuple(unique.values()), tuple(errors)


def _failed_verification(
    explanation: str,
    *,
    evidence_ids: tuple[str, ...] = (),
    coverage: float = 0.0,
) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.INSUFFICIENT,
        explanation=explanation,
        evidence_ids=evidence_ids,
        coverage=coverage,
    )


def _claim_with_failure(claim: Claim, failure: VerificationResult) -> Claim:
    try:
        return _verified_claim(claim, failure)
    except Exception:
        return claim


def _verified_claim(claim: Claim, result: VerificationResult) -> Claim:
    metadata = {
        **claim.metadata,
        "verification": {
            "status": result.status.value,
            "explanation": result.explanation,
            "coverage": result.coverage,
        },
    }
    return Claim.model_validate(
        {
            **claim.model_dump(),
            "evidence_ids": (
                result.evidence_ids if result.allows_publication else claim.evidence_ids
            ),
            "status": result.status.value,
            "confidence": result.coverage,
            "metadata": metadata,
        }
    )


def _render_report(
    question: str,
    claims: Sequence[Claim],
    citations: Sequence[Citation],
) -> str:
    citations_by_claim: dict[str, list[str]] = {}
    for citation in citations:
        citations_by_claim.setdefault(citation.claim_id, []).append(
            citation.label or citation.citation_id
        )
    lines = ["# Local evidence report", "", f"**Question:** {question}", ""]
    for claim in claims:
        labels = " ".join(citations_by_claim.get(claim.claim_id, ()))
        lines.append(f"- {claim.text} {labels}".rstrip())
    return "\n".join(lines)
