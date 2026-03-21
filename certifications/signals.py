"""
Signal handlers for the certifications app.

Auto-creates/updates Certification records when BusinessEvents
with business_type='certification' are saved.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .constants import BUSINESS_EVENT_TYPE_MAP, VERIFIER_REGISTRY

logger = logging.getLogger(__name__)


@receiver(post_save, sender="history.BusinessEvent")
def sync_business_event_certification(sender, instance, created, **kwargs):
    """
    When a BusinessEvent with business_type='certification' is saved,
    auto-create or update a Certification record on the establishment.
    """
    if instance.business_type != "certification":
        return

    if not instance.certification_type:
        return

    # Navigate to establishment: BusinessEvent → History → Parcel → Establishment
    try:
        history = instance.history
        if not history or not history.parcel or not history.parcel.establishment:
            logger.warning(f"BusinessEvent {instance.id}: cannot resolve establishment")
            return
        establishment = history.parcel.establishment
    except Exception as e:
        logger.warning(f"BusinessEvent {instance.id}: error resolving establishment: {e}")
        return

    # Map BusinessEvent certification_type to Certification certification_type
    mapped_type = BUSINESS_EVENT_TYPE_MAP.get(instance.certification_type)
    if not mapped_type:
        logger.info(
            f"BusinessEvent {instance.id}: unmapped certification_type "
            f"'{instance.certification_type}', skipping auto-sync"
        )
        return

    # Import here to avoid circular imports
    from .models import Certification

    # Build defaults from the event data
    defaults = {}
    if instance.verified_certifier_name:
        defaults["certifier_name"] = instance.verified_certifier_name
    if instance.certificate_number:
        defaults["certification_number"] = instance.certificate_number

    cert, was_created = Certification.objects.get_or_create(
        establishment=establishment,
        certification_type=mapped_type,
        defaults={
            "verification_status": "self_reported",
            **defaults,
        },
    )

    if not was_created and defaults:
        # Update existing cert with new data from the event
        updated = False
        for field, value in defaults.items():
            if value and getattr(cert, field) != value:
                setattr(cert, field, value)
                updated = True
        if updated:
            cert.save(update_fields=list(defaults.keys()) + ["updated_at"])

    # Trigger verification if supported and cert is new or still self_reported
    if was_created or cert.verification_status == "self_reported":
        if mapped_type in VERIFIER_REGISTRY:
            _trigger_background_verification(cert.id)

    action = "created" if was_created else "updated"
    logger.info(
        f"BusinessEvent {instance.id} → Certification {cert.id} "
        f"({mapped_type}) {action} for establishment {establishment.name}"
    )


def _trigger_background_verification(cert_id):
    """Trigger verification in background thread."""
    import threading

    from django.db import connections, transaction

    def _bg_verify():
        try:
            connections.close_all()
            from .models import Certification
            from .services.verification_manager import VerificationManager

            cert = Certification.objects.get(id=cert_id)
            manager = VerificationManager()
            manager.verify_certification(cert)
        except Exception as e:
            logger.error(f"Background verification from signal failed for cert {cert_id}: {e}")
        finally:
            connections.close_all()

    transaction.on_commit(lambda: threading.Thread(target=_bg_verify, daemon=True).start())
