"""Semantic verification tests that require no model service."""

from __future__ import annotations

import json
from types import SimpleNamespace

from scholarmind.models import Claim, Evidence, EvidenceLocator, Source, SourceKind
from scholarmind.verification import (
    OpenAISemanticEntailmentProvider,
    SemanticClaimVerifier,
    SemanticVerdict,
    VerificationStatus,
)


def _evidence(text: str, *, chunk: str = "semantic-test") -> Evidence:
    source = Source.create(
        kind=SourceKind.PAPER,
        title="Synthetic semantic verification study",
        uri="file:///papers/semantic-test.pdf",
    )
    return Evidence.create(
        source_id=source.source_id,
        text=text,
        locator=EvidenceLocator(page_number=2, chunk_id=chunk),
    )


def _claim(text: str, item: Evidence) -> Claim:
    return Claim.create(text=text, evidence_ids=(item.evidence_id,))


class _Provider:
    def __init__(self, verdict: SemanticVerdict | Exception) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def classify(self, claim: str, evidence: tuple[str, ...]) -> SemanticVerdict:
        self.calls.append((claim, evidence))
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def test_semantics_can_accept_a_supported_paraphrase() -> None:
    evidence = _evidence(
        "Fewer participants died after receiving the intervention."
    )
    claim = _claim("The intervention lowered mortality.", evidence)
    provider = _Provider(
        SemanticVerdict(
            status=VerificationStatus.SUPPORTED,
            confidence=0.94,
            reason="The two statements express the same outcome.",
            supporting_indices=(1,),
        )
    )

    result = SemanticClaimVerifier(provider).verify(claim, [evidence])

    assert result.status is VerificationStatus.SUPPORTED
    assert result.allows_publication
    assert result.verification_method == "semantic"
    assert result.evidence_ids == (evidence.evidence_id,)
    assert result.confidence == 0.94
    assert len(provider.calls) == 1


def test_numeric_hard_gate_cannot_be_overridden_by_model() -> None:
    evidence = _evidence("The method improves accuracy by 12%.")
    claim = _claim("The method improves accuracy by 99%.", evidence)
    provider = _Provider(
        SemanticVerdict(
            status=VerificationStatus.SUPPORTED,
            confidence=1.0,
            reason="Incorrect model answer.",
            supporting_indices=(1,),
        )
    )

    result = SemanticClaimVerifier(provider).verify(claim, [evidence])

    assert result.status is VerificationStatus.CONTRADICTED
    assert not result.hard_gate_passed
    assert result.verification_method == "deterministic"
    assert provider.calls == []


def test_low_confidence_semantic_support_is_not_publishable() -> None:
    evidence = _evidence("Fewer participants died after treatment.")
    claim = _claim("The treatment lowered mortality.", evidence)
    provider = _Provider(
        SemanticVerdict(
            status=VerificationStatus.SUPPORTED,
            confidence=0.6,
            reason="Likely a paraphrase.",
            supporting_indices=(1,),
        )
    )

    result = SemanticClaimVerifier(provider, minimum_confidence=0.75).verify(
        claim, [evidence]
    )

    assert result.status is VerificationStatus.INSUFFICIENT
    assert not result.allows_publication
    assert "below the publication threshold" in result.explanation


def test_provider_failure_fails_closed_without_losing_diagnostics() -> None:
    evidence = _evidence("Fewer participants died after treatment.")
    claim = _claim("The treatment lowered mortality.", evidence)

    result = SemanticClaimVerifier(_Provider(TimeoutError("offline"))).verify(
        claim, [evidence]
    )

    assert not result.allows_publication
    assert result.verification_method == "semantic-fallback"
    assert "TimeoutError" in result.explanation


def test_openai_provider_requests_and_parses_strict_json_schema() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "label": "contradicted",
                            "confidence": 0.97,
                            "reason": "The comparison direction is reversed.",
                            "supporting_indices": [1],
                        }
                    )
                )
            )
        ]
    )

    class Completions:
        def __init__(self) -> None:
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return response

    completions = Completions()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    provider = OpenAISemanticEntailmentProvider(
        model="qwen3-test",
        base_url="http://[::1]:8000/v1",
        client=client,
    )

    verdict = provider.classify("A outperforms B.", ("B outperforms A.",))

    assert verdict.status is VerificationStatus.CONTRADICTED
    assert verdict.supporting_indices == (1,)
    assert completions.kwargs["temperature"] == 0
    assert completions.kwargs["response_format"]["type"] == "json_schema"
