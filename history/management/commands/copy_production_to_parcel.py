"""
Copy an existing production (History) and ALL related entities to a different parcel,
assigning it as the parcel's current production.

Usage:
    poetry run python manage.py copy_production_to_parcel 301 106

This creates an exact duplicate of production 301 with:
- All 8 event types cloned (with signals disabled to preserve exact carbon values)
- All CarbonEntry records copied exactly
- CarbonCertification, CarbonReport records copied
- ConsumerTrustMetric, CarbonIntelligence copied
- HistoryScans, Reviews, MicroOffsets copied
- SustainabilityBadge M2M relationships preserved
- New production assigned as current_history on target parcel
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.signals import post_delete, post_save

from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from history.signals import (
    calculate_chemical_event_carbon,
    calculate_equipment_event_carbon,
    calculate_general_event_carbon,
    calculate_pest_management_event_carbon,
    calculate_production_event_carbon,
    calculate_soil_management_event_carbon,
    calculate_weather_event_carbon,
    cleanup_carbon_entries_on_event_delete,
)
from product.models import Parcel

EVENT_MODELS = [
    ("weather", WeatherEvent, "history_weatherevent_events"),
    ("chemical", ChemicalEvent, "history_chemicalevent_events"),
    ("production", ProductionEvent, "history_productionevent_events"),
    ("general", GeneralEvent, "history_generalevent_events"),
    ("equipment", EquipmentEvent, "history_equipmentevent_events"),
    ("soil_management", SoilManagementEvent, "history_soilmanagementevent_events"),
    ("pest_management", PestManagementEvent, "history_pestmanagementevent_events"),
    ("business", BusinessEvent, "history_businessevent_events"),
]

# Map event models to their post_save signal handlers
SIGNAL_HANDLERS = {
    ChemicalEvent: [(post_save, calculate_chemical_event_carbon)],
    ProductionEvent: [(post_save, calculate_production_event_carbon)],
    WeatherEvent: [(post_save, calculate_weather_event_carbon)],
    GeneralEvent: [(post_save, calculate_general_event_carbon)],
    EquipmentEvent: [(post_save, calculate_equipment_event_carbon)],
    SoilManagementEvent: [(post_save, calculate_soil_management_event_carbon)],
    PestManagementEvent: [(post_save, calculate_pest_management_event_carbon)],
}

# All event models that have the cleanup signal on delete
DELETE_SIGNAL_MODELS = [
    ChemicalEvent,
    ProductionEvent,
    WeatherEvent,
    GeneralEvent,
]


def disconnect_signals():
    """Disconnect all event carbon calculation signals"""
    for model_class, handlers in SIGNAL_HANDLERS.items():
        for signal, handler in handlers:
            signal.disconnect(handler, sender=model_class)
    for model_class in DELETE_SIGNAL_MODELS:
        post_delete.disconnect(cleanup_carbon_entries_on_event_delete, sender=model_class)


def reconnect_signals():
    """Reconnect all event carbon calculation signals"""
    for model_class, handlers in SIGNAL_HANDLERS.items():
        for signal, handler in handlers:
            signal.connect(handler, sender=model_class)
    for model_class in DELETE_SIGNAL_MODELS:
        post_delete.connect(cleanup_carbon_entries_on_event_delete, sender=model_class)


def clone_model_instance(instance, overrides=None):
    """
    Clone a Django model instance by copying all field values.
    Returns unsaved instance with pk=None.
    """
    clone = instance.__class__()
    for field in instance._meta.fields:
        if field.name == "id" or field.primary_key:
            continue
        setattr(clone, field.name, getattr(instance, field.name))
    if overrides:
        for key, value in overrides.items():
            setattr(clone, key, value)
    return clone


class Command(BaseCommand):
    help = "Copy a production with ALL related entities to a different parcel"

    def add_arguments(self, parser):
        parser.add_argument("production_id", type=int, help="ID of the production to copy")
        parser.add_argument("parcel_id", type=int, help="ID of the target parcel")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be copied without making changes",
        )

    def handle(self, *args, **options):
        production_id = options["production_id"]
        parcel_id = options["parcel_id"]
        dry_run = options["dry_run"]

        # Validate source production
        try:
            original = History.objects.get(pk=production_id)
        except History.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Production {production_id} not found"))
            return

        # Validate target parcel
        try:
            target_parcel = Parcel.objects.get(pk=parcel_id)
        except Parcel.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Parcel {parcel_id} not found"))
            return

        self.stdout.write(f"\nSource: Production #{original.pk} - {original.name}")
        self.stdout.write(f"  Parcel: {original.parcel.name if original.parcel else 'None'}")
        self.stdout.write(f"  Product: {original.product.name if original.product else 'None'}")
        self.stdout.write(f"  Start: {original.start_date}")
        self.stdout.write(f"  Finish: {original.finish_date}")
        self.stdout.write(f"  Published: {original.published}")
        self.stdout.write(f"\nTarget: Parcel #{target_parcel.pk} - {target_parcel.name}")

        if target_parcel.current_history:
            self.stdout.write(
                self.style.WARNING(
                    f"  WARNING: Parcel already has current_history = #{target_parcel.current_history.pk}"
                )
            )

        # Count related entities
        self._print_entity_counts(original)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n--dry-run: No changes made."))
            return

        # Perform the copy
        self.stdout.write(self.style.NOTICE("\nStarting copy..."))

        try:
            with transaction.atomic():
                new_production = self._copy_production(original, target_parcel)
                self._copy_events(original, new_production)
                self._copy_carbon_entries(original, new_production)
                self._copy_carbon_certifications(original, new_production)
                self._copy_carbon_reports(original, new_production)
                self._copy_consumer_trust_metric(original, new_production)
                self._copy_carbon_intelligence(original, new_production)
                self._copy_history_scans(original, new_production)
                self._copy_reviews(original, new_production)
                self._copy_micro_offsets(original, new_production)
                self._copy_sustainability_badges(original, new_production)

                # Set as current production for target parcel
                target_parcel.current_history = new_production
                target_parcel.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nDone! New production #{new_production.pk} created "
                        f"and set as current_history for Parcel #{target_parcel.pk}."
                        f"\n  Consumer URL: /production/{new_production.pk}"
                    )
                )

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"\nError during copy: {e}"))
            raise

    def _print_entity_counts(self, original):
        """Print counts of all related entities"""
        from carbon.models import (
            CarbonCertification,
            CarbonEntry,
            CarbonIntelligence,
            CarbonReport,
            ConsumerTrustMetric,
            MicroOffset,
            SustainabilityBadge,
        )
        from reviews.models import Review

        self.stdout.write("\nRelated entities:")
        total_events = 0
        for label, model_class, related_name in EVENT_MODELS:
            count = getattr(original, related_name).count()
            if count > 0:
                self.stdout.write(f"  {label} events: {count}")
            total_events += count
        self.stdout.write(f"  TOTAL events: {total_events}")

        carbon_count = CarbonEntry.objects.filter(production=original).count()
        self.stdout.write(f"  CarbonEntry: {carbon_count}")

        cert_count = CarbonCertification.objects.filter(production=original).count()
        self.stdout.write(f"  CarbonCertification: {cert_count}")

        report_count = CarbonReport.objects.filter(production=original).count()
        self.stdout.write(f"  CarbonReport: {report_count}")

        trust_exists = ConsumerTrustMetric.objects.filter(production=original).exists()
        self.stdout.write(f"  ConsumerTrustMetric: {'1' if trust_exists else '0'}")

        intel_exists = CarbonIntelligence.objects.filter(production=original).exists()
        self.stdout.write(f"  CarbonIntelligence: {'1' if intel_exists else '0'}")

        scan_count = HistoryScan.objects.filter(history=original).count()
        self.stdout.write(f"  HistoryScan: {scan_count}")

        review_count = Review.objects.filter(production=original).count()
        self.stdout.write(f"  Review: {review_count}")

        offset_count = MicroOffset.objects.filter(production=original).count()
        self.stdout.write(f"  MicroOffset: {offset_count}")

        badge_count = SustainabilityBadge.objects.filter(productions=original).count()
        self.stdout.write(f"  SustainabilityBadge: {badge_count}")

    def _copy_production(self, original, target_parcel):
        """Copy the History (production) record"""
        new_prod = clone_model_instance(
            original,
            overrides={
                "parcel": target_parcel,
                "public_views": original.public_views,
                "unique_visitors": original.unique_visitors,
            },
        )
        # Let save() generate new QR code
        new_prod.save()
        self.stdout.write(self.style.SUCCESS(f"  Created production #{new_prod.pk} (copy of #{original.pk})"))
        return new_prod

    def _copy_events(self, original, new_production):
        """Copy all 8 event types with signals disconnected"""
        disconnect_signals()
        try:
            total = 0
            for label, model_class, related_name in EVENT_MODELS:
                events = getattr(original, related_name).all()
                count = 0
                for event in events:
                    new_event = clone_model_instance(
                        event,
                        overrides={
                            "history": new_production,
                        },
                    )
                    new_event.save()
                    count += 1
                if count > 0:
                    self.stdout.write(f"  Copied {count} {label} event(s)")
                total += count
            self.stdout.write(self.style.SUCCESS(f"  Total events copied: {total}"))
        finally:
            reconnect_signals()

    def _copy_carbon_entries(self, original, new_production):
        """Copy CarbonEntry records exactly"""
        from carbon.models import CarbonEntry

        entries = CarbonEntry.objects.filter(production=original)
        count = 0
        for entry in entries:
            new_entry = clone_model_instance(
                entry,
                overrides={
                    "production": new_production,
                },
            )
            new_entry.save()
            count += 1
        if count > 0:
            self.stdout.write(f"  Copied {count} CarbonEntry record(s)")

    def _copy_carbon_certifications(self, original, new_production):
        """Copy CarbonCertification records"""
        from carbon.models import CarbonCertification

        certs = CarbonCertification.objects.filter(production=original)
        count = 0
        for cert in certs:
            new_cert = clone_model_instance(
                cert,
                overrides={
                    "production": new_production,
                    "certificate_id": f"{cert.certificate_id}-copy-{new_production.pk}",
                },
            )
            new_cert.save()
            count += 1
        if count > 0:
            self.stdout.write(f"  Copied {count} CarbonCertification record(s)")

    def _copy_carbon_reports(self, original, new_production):
        """Copy CarbonReport records"""
        from carbon.models import CarbonReport

        reports = CarbonReport.objects.filter(production=original)
        count = 0
        for report in reports:
            new_report = clone_model_instance(
                report,
                overrides={
                    "production": new_production,
                },
            )
            new_report.save()
            count += 1
        if count > 0:
            self.stdout.write(f"  Copied {count} CarbonReport record(s)")

    def _copy_consumer_trust_metric(self, original, new_production):
        """Copy ConsumerTrustMetric (OneToOne)"""
        from carbon.models import ConsumerTrustMetric

        try:
            metric = ConsumerTrustMetric.objects.get(production=original)
            new_metric = clone_model_instance(
                metric,
                overrides={
                    "production": new_production,
                },
            )
            new_metric.save()
            self.stdout.write("  Copied ConsumerTrustMetric")
        except ConsumerTrustMetric.DoesNotExist:
            pass

    def _copy_carbon_intelligence(self, original, new_production):
        """Copy CarbonIntelligence (OneToOne)"""
        from carbon.models import CarbonIntelligence

        try:
            intel = CarbonIntelligence.objects.get(production=original)
            new_intel = clone_model_instance(
                intel,
                overrides={
                    "production": new_production,
                },
            )
            new_intel.save()
            self.stdout.write("  Copied CarbonIntelligence")
        except CarbonIntelligence.DoesNotExist:
            pass

    def _copy_history_scans(self, original, new_production):
        """Copy HistoryScan records"""
        scans = HistoryScan.objects.filter(history=original)
        count = 0
        for scan in scans:
            new_scan = clone_model_instance(
                scan,
                overrides={
                    "history": new_production,
                    "original_scan": None,  # Don't link to original's duplicate chain
                },
            )
            new_scan.save()
            count += 1
        if count > 0:
            self.stdout.write(f"  Copied {count} HistoryScan record(s)")

    def _copy_reviews(self, original, new_production):
        """Copy Review records"""
        from reviews.models import Review

        reviews = Review.objects.filter(production=original)
        count = 0
        for review in reviews:
            new_review = clone_model_instance(
                review,
                overrides={
                    "production": new_production,
                    "scan": None,  # Don't link to original scan
                },
            )
            new_review.save()
            count += 1
        if count > 0:
            self.stdout.write(f"  Copied {count} Review record(s)")

    def _copy_micro_offsets(self, original, new_production):
        """Copy MicroOffset records"""
        from carbon.models import MicroOffset

        offsets = MicroOffset.objects.filter(production=original)
        count = 0
        for offset in offsets:
            new_offset = clone_model_instance(
                offset,
                overrides={
                    "production": new_production,
                },
            )
            new_offset.save()
            count += 1
        if count > 0:
            self.stdout.write(f"  Copied {count} MicroOffset record(s)")

    def _copy_sustainability_badges(self, original, new_production):
        """Copy SustainabilityBadge M2M relationships"""
        from carbon.models import SustainabilityBadge

        badges = SustainabilityBadge.objects.filter(productions=original)
        count = 0
        for badge in badges:
            badge.productions.add(new_production)
            count += 1
        if count > 0:
            self.stdout.write(f"  Linked {count} SustainabilityBadge(s)")
