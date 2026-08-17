"""Claim-to-evidence verification and publication gates."""

from scholarmind.verification.claim_verifier import (
    ClaimVerificationProvider,
    ClaimVerifier,
    VerificationResult,
    VerificationStatus,
)
from scholarmind.verification.semantic_verifier import (
    OpenAISemanticEntailmentProvider,
    SemanticClaimVerifier,
    SemanticEntailmentProvider,
    SemanticVerdict,
)

__all__ = [
    "ClaimVerificationProvider",
    "ClaimVerifier",
    "VerificationResult",
    "VerificationStatus",
    "OpenAISemanticEntailmentProvider",
    "SemanticClaimVerifier",
    "SemanticEntailmentProvider",
    "SemanticVerdict",
]
