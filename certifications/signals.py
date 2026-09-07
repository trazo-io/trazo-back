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

    cert, was_created = _resolve_certification(Certification, establishment, mapped_type, defaults)

    # Update the matched row with what the event names — but never rewrite the identity of a
    # certificate that has already been VERIFIED against the certifier's own register. A
    # self-reported event is weaker evidence than the USDA Organic Integrity Database match
    # that set `verified`, and letting it overwrite the certifier name or number would turn a
    # verified row into an unverified claim wearing a verified badge.
    if not was_created and defaults and cert.verification_status != "verified":
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


def _resolve_certification(Certification, establishment, mapped_type, defaults):
    """Find the Certification row a business event is about, or create one.

    Returns ``(cert, was_created)``.

    🔴 2026-09-06. This was ``get_or_create(establishment=…, certification_type=…)``, and an
    operation with two certificates of one type — the demo farm carries a verified COC USDA
    Organic row beside a pending CCOF one, which is exactly what a grower switching certifiers
    looks like — raised ``MultipleObjectsReturned`` inside ``post_save``. The row was already
    written; the request still answered 500, the wizard said "Failed to create event", and the
    farmer could not log a certification event at all. The ``(establishment, certification_type)``
    pair is not unique on the model and must not be treated as a key.

    Resolution order, most specific first:
      1. same certificate number            → that row;
      2. same certifier name (case-insensitive) → that row;
      3. the event names neither             → the operation's existing row of that type, if one;
      4. the event names a DIFFERENT certifier or number → a new row. A second certifier is a
         second certificate, not a correction to the first.
    """
    rows = Certification.objects.filter(establishment=establishment, certification_type=mapped_type)
    number = (defaults.get("certification_number") or "").strip()
    name = (defaults.get("certifier_name") or "").strip()

    cert = None
    if number:
        cert = rows.filter(certification_number__iexact=number).order_by("pk").first()
    if cert is None and name:
        cert = rows.filter(certifier_name__iexact=name).order_by("pk").first()
    if cert is None and not number and not name:
        cert = rows.order_by("pk").first()
    if cert is not None:
        return cert, False

    cert = Certification.objects.create(
        establishment=establishment,
        certification_type=mapped_type,
        verification_status="self_reported",
        **defaults,
    )
    return cert, True


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


# Sprint 5.1 — OSP ↔ events drift detector. Attach post_save handlers on
# ChemicalEvent + SoilManagementEvent. Safe to import here: this module is
# loaded from CertificationsConfig.ready(), so both apps are resolved by then.
from certifications.services.drift_detector import attach_signals as _attach_drift_signals  # noqa: E402

_attach_drift_signals()
