"""
Verification Manager — orchestrates certification verification
across all supported verifiers.
"""

import importlib
import logging
from typing import Optional

from django.utils import timezone

from ..constants import VERIFIER_REGISTRY
from ..models import Certification, CertificationVerificationLog
from .base_verifier import BaseCertificationVerifier, VerificationResult

logger = logging.getLogger(__name__)


class VerificationManager:
    """Orchestrates certification verification across all supported verifiers."""

    def __init__(self):
        self._verifiers = {}

    def _get_verifier(self, certification_type: str) -> Optional[BaseCertificationVerifier]:
        """Load and cache verifier instances from the registry."""
        if certification_type in self._verifiers:
            return self._verifiers[certification_type]

        dotted_path = VERIFIER_REGISTRY.get(certification_type)
        if not dotted_path:
            return None

        try:
            module_path, class_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            verifier_class = getattr(module, class_name)
            verifier = verifier_class()
            self._verifiers[certification_type] = verifier
            return verifier
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to load verifier for {certification_type}: {e}")
            return None

    def verify_certification(self, certification: Certification) -> VerificationResult:
        """
        Verify a single certification using the appropriate verifier.
        Updates the Certification model and creates an audit log entry.
        """
        status_before = certification.verification_status

        # Get the verifier for this certification type
        verifier = self._get_verifier(certification.certification_type)

        if verifier is None:
            # No verifier available — mark as self-reported
            if certification.verification_status == "pending":
                certification.verification_status = "self_reported"
                certification.verification_notes = "No automated verification available for this certification type"
                certification.save(update_fields=["verification_status", "verification_notes", "updated_at"])

            CertificationVerificationLog.objects.create(
                certification=certification,
                status_before=status_before,
                status_after=certification.verification_status,
                verification_source="none",
                success=False,
                error_message="No verifier registered for this certification type",
            )

            return VerificationResult(
                found=False,
                status="self_reported",
                notes="No automated verification available",
            )

        # Get establishment details for the search
        # Use USDA operation name if provided (farmer's registered name may differ)
        establishment = certification.establishment
        operation_name = certification.usda_operation_name or establishment.name
        state = establishment.state or ""

        if not operation_name:
            logger.warning(f"Certification {certification.id}: establishment has no name")
            return VerificationResult(
                found=False,
                status="self_reported",
                error="Establishment name is required for verification",
            )

        # Run verification
        logger.info(
            f"Verifying certification {certification.id} "
            f"({certification.certification_type}) for '{operation_name}' in {state}"
        )

        result = verifier.verify(
            operation_name=operation_name,
            state=state,
            certification_number=certification.certification_number,
        )

        # Update the certification model
        # "not_found" means the farm isn't in our data yet — keep as "pending"
        # so the monthly re-verification retries it after the next data refresh.
        # Only "verified", "revoked", "suspended", "expired" are final states.
        if result.status == "not_found":
            effective_status = "pending"
        else:
            effective_status = result.status
        certification.verification_status = effective_status
        certification.last_verified_at = timezone.now()
        certification.verification_source = verifier.source_identifier

        update_fields = [
            "verification_status",
            "last_verified_at",
            "verification_source",
            "updated_at",
        ]

        if result.source_url:
            certification.verification_source_url = result.source_url
            update_fields.append("verification_source_url")

        if result.raw_response:
            certification.raw_api_response = result.raw_response
            update_fields.append("raw_api_response")

        if result.notes:
            certification.verification_notes = result.notes
            update_fields.append("verification_notes")

        if result.certifier_name and not certification.certifier_name:
            certification.certifier_name = result.certifier_name
            update_fields.append("certifier_name")

        if result.effective_date and not certification.effective_date:
            certification.effective_date = self._parse_date(result.effective_date)
            if certification.effective_date:
                update_fields.append("effective_date")

        if result.expiry_date and not certification.expiry_date:
            certification.expiry_date = self._parse_date(result.expiry_date)
            if certification.expiry_date:
                update_fields.append("expiry_date")

        if result.certification_scope and not certification.certification_scope:
            certification.certification_scope = result.certification_scope
            update_fields.append("certification_scope")

        if result.certified_items and not certification.certified_items:
            certification.certified_items = result.certified_items
            update_fields.append("certified_items")

        certification.save(update_fields=update_fields)

        # Create audit log
        CertificationVerificationLog.objects.create(
            certification=certification,
            status_before=status_before,
            status_after=result.status,
            verification_source=verifier.source_identifier,
            success=result.found,
            error_message=result.error,
            raw_response=result.raw_response,
        )

        logger.info(
            f"Certification {certification.id}: "
            f"{status_before} → {effective_status} "
            f"(confidence: {result.confidence_score:.0%})"
        )

        return result

    @staticmethod
    def _parse_date(date_str):
        """Parse date from various formats (USDA uses MM/DD/YYYY)."""
        if not date_str:
            return None
        from datetime import datetime

        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except (ValueError, AttributeError):
                continue
        return None

    def reverify_all_active(self, days_ahead: int = 30):
        """
        Batch re-verify all active certifications.
        Prioritizes those expiring soon.
        """
        cutoff = timezone.now().date() + timezone.timedelta(days=days_ahead)

        # Re-verify: verified certs, pending certs (not yet in data), and self_reported
        certs_to_verify = Certification.objects.filter(
            verification_status__in=["verified", "self_reported", "pending"],
            certification_type__in=VERIFIER_REGISTRY.keys(),
        ).select_related("establishment")

        # Prioritize expiring certs
        expiring = certs_to_verify.filter(expiry_date__lte=cutoff).order_by("expiry_date")
        non_expiring = certs_to_verify.exclude(expiry_date__lte=cutoff)

        total = 0
        changed = 0

        for cert in list(expiring) + list(non_expiring):
            try:
                old_status = cert.verification_status
                self.verify_certification(cert)
                total += 1
                if cert.verification_status != old_status:
                    changed += 1
            except Exception as e:
                logger.error(f"Re-verification failed for cert {cert.id}: {e}")
                total += 1

        logger.info(f"Batch re-verification complete: {total} checked, {changed} status changes")
        return {"total": total, "changed": changed}
