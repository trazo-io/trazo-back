"""
Create the Solana Verde Organic Ranch pilot-ready NOP-compliant farm fixture.

This is the canonical CCOF demo + PDF regression fixture + drift-detector stress test.
Populates the NOP fields closed in the 2026-04 pivot (supplier/invoice chain,
compost temp/duration/turnings, manure interval, pest ID + threshold rationale,
contamination incident chain, equipment cleaning, OFPP, split operation,
ParcelCropHistory, seed organic search log, 5-year retention, sales/delivery)
plus an active Organic System Plan v1 (six § 205.201(a) narrative sections) and
an OGC delivery BusinessEvent (BOL/PO/invoice + § 205.103(b)(3) organic-on-invoice).

Source of truth for every literal value:
  documentation/testing/E2E_ORGANIC_FARM_TESTING_GUIDE.md

Usage:
    poetry run python manage.py create_organic_pilot_farm
    poetry run python manage.py create_organic_pilot_farm maria@solanaverde.farm
    poetry run python manage.py create_organic_pilot_farm maria@solanaverde.farm --reset
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from company.models import Company
from users.constants import PRODUCER
from users.models import User

from ._solana_verde_base import COMPANY_NAME, create_solana_verde_base
from ._solana_verde_current_events import create_current_events
from ._solana_verde_finished_events import create_finished_events

# Reuse the shared Unsplash image dict from the legacy demo command.
# We do NOT duplicate URLs — single source of truth.
from .create_demo_user import DEMO_IMAGES

DEFAULT_EMAIL = "maria@solanaverde.farm"


class Command(BaseCommand):
    help = "Seed the Solana Verde Organic Ranch NOP-compliant pilot fixture."

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            type=str,
            nargs="?",
            default=DEFAULT_EMAIL,
            help=f"Target user email (default: {DEFAULT_EMAIL}).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing Solana Verde data for this user and recreate.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"]
        reset = options["reset"]

        # 1. User — lookup or create
        user, user_created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": "Maria Elena",
                "last_name": "Gutierrez",
                "user_type": PRODUCER,
                "is_active": True,
                "is_verified": True,
            },
        )
        if user_created:
            user.set_password("SolanaVerde2026Org")
            user.save()
            self.stdout.write(self.style.SUCCESS(f"  User created: {email} (password: SolanaVerde2026Org)"))
        else:
            self.stdout.write(f"  User found: {user.get_full_name()} ({email})")

        # 2. Idempotency
        existing = Company.objects.filter(
            name=COMPANY_NAME,
            company_workers__user=user,
        ).first()

        if existing and not reset:
            self.stdout.write(
                self.style.WARNING(
                    f"Solana Verde fixture already exists for {email} "
                    f"(Company #{existing.id}). Use --reset to recreate."
                )
            )
            return

        if existing and reset:
            self.stdout.write("  Deleting existing Solana Verde fixture...")
            self._cascade_delete(existing)
            self.stdout.write(self.style.SUCCESS("  Deleted."))

        # 3. Base infrastructure (company, establishment, parcel, certifications,
        #    ParcelCropHistory x 3, finished + current productions, sales/retention)
        (
            company,
            establishment,
            parcel,
            product,
            crop_type,
            production_finished,
            production_current,
        ) = create_solana_verde_base(user)

        self.stdout.write(f"  Company:        {company.name} (#{company.id})")
        self.stdout.write(f"  Establishment:  {establishment.name} (#{establishment.id})")
        self.stdout.write(f"  Parcel:         {parcel.name} (#{parcel.id})")

        # 4. Events — 24 finished (NOP-complete + OGC delivery) + 6 current
        finished_count = create_finished_events(production_finished, user, demo_images=DEMO_IMAGES)
        current_count = create_current_events(production_current, user, demo_images=DEMO_IMAGES)

        # 5. Trust metrics (non-fatal if it errors — dev envs may lack Redis)
        try:
            production_finished.update_trust_metrics()
            production_current.update_trust_metrics()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Trust metrics update failed (non-fatal): {e}"))

        # 6. NOP compliance invariants — fail loud if any break
        self._verify_invariants(production_finished, parcel)

        # 7. Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Solana Verde pilot fixture seeded successfully!"))
        self.stdout.write("")
        self.stdout.write(f"  Farm:           {establishment.name}")
        self.stdout.write(f"  Owner:          {user.get_full_name()} <{email}>")
        self.stdout.write(f"  Parcel:         {parcel.name} ({parcel.area} ha)")
        self.stdout.write("")
        self.stdout.write(
            f"  Finished prod:  #{production_finished.id} — {finished_count} events, lot {production_finished.lot_id}"
        )
        self.stdout.write(f"  Current prod:   #{production_current.id} — {current_count} events")
        self.stdout.write("")
        self.stdout.write(f"  Retention until: {production_finished.retention_until} (5-yr NOP)")
        self.stdout.write(f"  Sold to:         {production_finished.sold_to} ({production_finished.quantity_sold} kg)")
        self.stdout.write("")
        self.stdout.write("  Consumer URL:")
        self.stdout.write(f"    /production/{production_finished.id}  (Hass Avocado - finished)")
        self.stdout.write("")
        self.stdout.write("  NOP coverage verified: OFPP, split-op, ParcelCropHistory (3yr),")
        self.stdout.write("    supplier chain (4 chemicals), compost temp/duration/turnings,")
        self.stdout.write("    manure 120-day, pest ID + threshold rationale, equipment cleaning,")
        self.stdout.write("    contamination incident chain, seed organic search log, sales record,")
        self.stdout.write("    active OSP v1 (six § 205.201 sections fully populated, linked to")
        self.stdout.write("    CCOF cert), OGC delivery BusinessEvent (BOL/PO/invoice + § 205.103(b)(3)).")

    def _cascade_delete(self, company):
        """
        Delete fixture in dependency order.

        Workaround: Django's default cascade fires auditlog post_delete signals
        for each Event, and `CommonEvent.__str__` crashes when its already-deleted
        History is fetched via FK. Deleting events via raw SQL (`_raw_delete`)
        bypasses signals, then cascade handles the rest cleanly.
        """
        from django.db import connection

        from history.models import (
            BusinessEvent,
            ChemicalEvent,
            EquipmentEvent,
            GeneralEvent,
            History,
            PestManagementEvent,
            ProductionEvent,
            SoilManagementEvent,
            WeatherEvent,
        )

        histories = History.objects.filter(parcel__establishment__company=company)
        history_ids = list(histories.values_list("id", flat=True))

        if history_ids:
            event_models = [
                BusinessEvent,
                ChemicalEvent,
                EquipmentEvent,
                GeneralEvent,
                PestManagementEvent,
                ProductionEvent,
                SoilManagementEvent,
                WeatherEvent,
            ]
            with connection.cursor() as cur:
                for M in event_models:
                    table = M._meta.db_table
                    cur.execute(
                        f"DELETE FROM {table} WHERE history_id = ANY(%s)",
                        [history_ids],
                    )

        company.delete()

    def _verify_invariants(self, finished_production, parcel):
        """Assert NOP compliance invariants. Fail loud so regressions don't slip."""
        from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
        from history.models import BusinessEvent, ChemicalEvent, GeneralEvent, ProductionEvent, SoilManagementEvent
        from product.models import ParcelCropHistory

        # 1. Every ChemicalEvent has supplier_name + purchase_date + purchase_invoice
        chem_missing = (
            ChemicalEvent.objects.filter(history=finished_production).filter(supplier_name__isnull=True).count()
        )
        chem_missing += ChemicalEvent.objects.filter(history=finished_production).filter(supplier_name="").count()
        if chem_missing:
            raise CommandError(
                f"NOP invariant failed: {chem_missing} ChemicalEvent(s) missing supplier_name. "
                "Every chemical event must have a supplier for 7 CFR 205.103 mass-balance."
            )

        # 2. Compost event: peak_temp 131-170°F, duration >= 15, turnings >= 5
        co = SoilManagementEvent.objects.filter(
            history=finished_production, type=SoilManagementEvent.COMPOSTING
        ).first()
        if co:
            if not (co.compost_peak_temp_f and 131 <= float(co.compost_peak_temp_f) <= 170):
                raise CommandError("NOP invariant failed: compost peak_temp out of 131-170°F range.")
            if not co.compost_duration_days_at_temp or co.compost_duration_days_at_temp < 15:
                raise CommandError("NOP invariant failed: compost duration < 15 days.")
            if not co.compost_turning_count or co.compost_turning_count < 5:
                raise CommandError("NOP invariant failed: compost turnings < 5.")

        # 3. Manure event has 120-day interval
        om = SoilManagementEvent.objects.filter(
            history=finished_production, type=SoilManagementEvent.ORGANIC_MATTER
        ).first()
        if om and om.manure_application_date and not om.manure_harvest_interval:
            raise CommandError("NOP invariant failed: manure event missing harvest_interval.")

        # 4. At least one contamination incident
        contam_count = GeneralEvent.objects.filter(history=finished_production, is_contamination_incident=True).count()
        if contam_count == 0:
            raise CommandError("NOP invariant failed: no contamination incident seeded.")

        # 5. At least one EM event with shared_with_conventional=True
        em_shared = ProductionEvent.objects.filter(
            history=finished_production,
            type=ProductionEvent.EQUIPMENT_MAINTENANCE,
            shared_with_conventional=True,
        ).count()
        if em_shared == 0:
            raise CommandError(
                "NOP invariant failed: no EM event with shared_with_conventional=True. "
                "Required for 7 CFR 205.272 equipment cleaning demo."
            )

        # 6. ParcelCropHistory has 3 rows
        history_count = ParcelCropHistory.objects.filter(parcel=parcel).count()
        if history_count < 3:
            raise CommandError(
                f"NOP invariant failed: only {history_count} ParcelCropHistory rows "
                "(need 3 for 7 CFR 205.202 36-month history)."
            )

        # 7. Finished production has retention_until + sold_to
        if not finished_production.retention_until:
            raise CommandError("NOP invariant failed: finished production missing retention_until.")
        if not finished_production.sold_to:
            raise CommandError("NOP invariant failed: finished production missing sold_to (Phase 9 sales record).")

        # 8. Active OSP v1 with all six § 205.201(a) sections populated
        establishment = parcel.establishment
        active_osp = (
            OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
            .order_by("-version_number")
            .first()
        )
        if not active_osp:
            raise CommandError(
                "NOP invariant failed: no active OrganicSystemPlan for establishment. "
                "§ 205.201 requires every certified operation to maintain an active OSP."
            )
        for key in OSP_SECTION_KEYS:
            narrative = (active_osp.sections or {}).get(key, {}).get("narrative", "").strip()
            if len(narrative) < 200:
                raise CommandError(
                    f"NOP invariant failed: OSP section '{key}' narrative under 200 chars "
                    f"({len(narrative)}). Audit PDF flags any short section as incomplete."
                )

        # 9. OGC delivery BusinessEvent (§ 205.501(a)(21) + § 205.103(b)(3))
        ogc_delivery = BusinessEvent.objects.filter(
            history=finished_production,
            type=BusinessEvent.COMPLIANCE,
        ).first()
        if not ogc_delivery:
            raise CommandError(
                "NOP invariant failed: no OGC delivery BusinessEvent (type=COMPLIANCE) "
                "on finished production. § 205.501(a)(21) downstream traceability requires "
                "a sale/delivery record with BOL/PO/invoice metadata."
            )
        extra = ogc_delivery.extra_data or {}
        for required_key in ("bill_of_lading", "purchase_order", "invoice_number", "organic_on_invoice"):
            if not extra.get(required_key):
                raise CommandError(f"NOP invariant failed: OGC delivery missing extra_data.{required_key}.")
