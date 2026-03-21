"""
Abstract base class for certification verifiers.
Each certification type (USDA Organic, CNG, ROC, etc.) gets its own
verifier implementation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    """Standardized result from any certification verifier."""

    found: bool
    status: str  # "verified", "not_found", "expired", "revoked", "suspended"
    certifier_name: Optional[str] = None
    effective_date: Optional[str] = None  # ISO date string
    expiry_date: Optional[str] = None
    certification_scope: Optional[str] = None
    certified_items: Optional[List[str]] = field(default_factory=list)
    source_url: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
    confidence_score: float = 0.0  # 0.0-1.0 for fuzzy matching
    notes: Optional[str] = None
    error: Optional[str] = None


class BaseCertificationVerifier(ABC):
    """Abstract base class for all certification verifiers."""

    @property
    @abstractmethod
    def verifier_name(self) -> str:
        """Human-readable name of this verifier."""
        pass

    @property
    @abstractmethod
    def source_identifier(self) -> str:
        """Short identifier for verification_source field (e.g., usda_organic_integrity_db)."""
        pass

    @property
    @abstractmethod
    def supported_certification_types(self) -> List[str]:
        """List of certification_type values this verifier handles."""
        pass

    @abstractmethod
    def verify(
        self,
        operation_name: str,
        state: str,
        certification_number: Optional[str] = None,
        **kwargs,
    ) -> VerificationResult:
        """
        Attempt to verify a certification.

        Args:
            operation_name: Name of the farm/establishment
            state: US state (2-letter abbreviation or full name)
            certification_number: Optional certificate number for direct lookup
            **kwargs: Additional verifier-specific parameters

        Returns:
            VerificationResult with verification outcome
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the external verification service is reachable."""
        pass
