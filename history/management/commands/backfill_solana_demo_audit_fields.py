"""
Kitchen-sink DEMO backfill for the Solana Verde avocado fixture.

Solana Verde is a demo fixture (NOT a real lead), so it is safe to populate EVERY
new audit-export section — including the ones that don't fit Leonard Loewen's
regenerative walnut operation. Use this to produce one audit PDF that exercises
all the 2026 audit additions at once.

Adds, idempotently, on the published Solana Verde production:
  * NOP 5006 — a documented processed-manure event (interval-exempt)
  * NOP 5012 — nitrogen_source on fertilizer events
  * NOP 5026 — residual chlorine at discharge on a post-harvest wash event
  * SOE (§ 205.307(a)) — itemized SalesRecords
  * NOP 2615 — both a § 205.400(f)(1) (immediate) and a § 205.400(f)(2) change notification

Usage:
    poetry run python manage.py backfill_solana_demo_audit_fields
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from company.models import Company
from history.models import ChemicalEvent, History, ProductionEvent, SalesRecord, SoilManagementEvent
from users.models import User

from ._solana_verde_base import COMPANY_NAME

SOLANA_SALES = [
    {
        "buyer_name": "Del Rey Avocado Co.",
        "sale_date": date(2026, 3, 14),
        "quantity": Decimal("18000.00"),
        "quantity_unit": "lb",
        "invoice_number": "SV-INV-2026-0112",
        "organic_on_invoice": True,
    },
    {
        "buyer_name": "Mission Produce (organic line)",
        "sale_date": date(2026, 3, 28),
        "quantity": Decimal("12500.00"),
        "quantity_unit": "lb",
        "invoice_number": "SV-INV-2026-0145",
        "organic_on_invoice": True,
    },
]


class Command(BaseCommand):
    help = "Kitchen-sink demo: populate ALL new audit sections on the Solana Verde fixture."

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, nargs="?", default=None, help="Optional owner email filter.")

    @transaction.atomic
    def handle(self, *args, **options):
        company_qs = Company.objects.filter(name=COMPANY_NAME)
        if options.get("email"):
            company_qs = company_qs.filter(company_workers__user__email=options["email"])
        company = company_qs.first()
        if company is None:
            self.stderr.write(self.style.ERROR(f"No '{COMPANY_NAME}' company found. Run create_organic_pilot_farm first."))
            return

        prod = (
            History.objects.filter(parcel__establishment__company=company, published=True)
            .order_by("-finish_date", "-id")
            .first()
        )
        if prod is None:
            self.stderr.write(self.style.ERROR("No published Solana Verde production found."))
            return

        self.stdout.write(f"  Production: {prod.name} (#{prod.id}, public_id={prod.public_id})")
        user = prod.operator
        establishment = prod.parcel.establishment

        # 1) NOP 5006 — a documented processed-manure soil event (reuse an OM event, else create one).
        soil = (
            prod.history_soilmanagementevent_events.filter(type=SoilManagementEvent.ORGANIC_MATTER).first()
            or prod.history_soilmanagementevent_events.filter(type=SoilManagementEvent.COMPOSTING).first()
        )
        if soil is None:
            soil = SoilManagementEvent(
                history=prod,
                created_by=user,
                description="Processed poultry-manure pellets applied to tree rows (pathogen-reduced).",
                date=timezone.now(),
                type=SoilManagementEvent.ORGANIC_MATTER,
            )
        soil.manure_application_date = soil.manure_application_date or date(2025, 12, 1)
        soil.manure_treatment = "processed_5006"
        soil.processed_manure_temp_f = Decimal("155.0")
        soil.processed_manure_attestation = "OMRI-listed heat-processed poultry pellets (PFRP), supplier COA on file"
        soil.skip_manure_validation = True
        soil.save()
        self.stdout.write(f"  NOP 5006 processed manure set on soil event #{soil.id}.")

        # 2) NOP 5012 — nitrogen source on fertilizer events.
        n = 0
        for ev in prod.history_chemicalevent_events.filter(type=ChemicalEvent.FERTILIZER):
            if not ev.nitrogen_source:
                ev.nitrogen_source = "organic"
                ev.save(update_fields=["nitrogen_source"])
                n += 1
        self.stdout.write(f"  NOP 5012 nitrogen_source set on {n} fertilizer event(s).")

        # 3) NOP 5026 — residual chlorine on a post-harvest wash / equipment event.
        wash = (
            prod.history_productionevent_events.filter(type=ProductionEvent.EQUIPMENT_MAINTENANCE).first()
            or prod.history_productionevent_events.filter(type=ProductionEvent.POST_HARVEST_PROCESSING).first()
        )
        if wash is None:
            wash = ProductionEvent(
                history=prod,
                created_by=user,
                description="Post-harvest wash-line sanitation.",
                date=timezone.now(),
                type=ProductionEvent.EQUIPMENT_MAINTENANCE,
            )
        wash.sanitizer_name = "Chlorine (sodium hypochlorite)"
        wash.sanitizer_ppm = Decimal("100.0")
        wash.sanitizer_residual_ppm_at_discharge = Decimal("3.8")
        wash.rinse_step_documented = True
        wash.sanitizer_nop_reference = "§ 205.605(b) - Sodium hypochlorite"
        wash.save()
        self.stdout.write(f"  NOP 5026 residual chlorine set on production event #{wash.id}.")

        # 4) SOE — itemized sales records.
        for s in SOLANA_SALES:
            SalesRecord.objects.get_or_create(
                production=prod,
                invoice_number=s["invoice_number"],
                defaults=dict(
                    buyer_name=s["buyer_name"],
                    sale_date=s["sale_date"],
                    quantity=s["quantity"],
                    quantity_unit=s["quantity_unit"],
                    organic_on_invoice=s["organic_on_invoice"],
                ),
            )
        self.stdout.write(f"  SOE sales records: {prod.sales_records.count()} total.")

        # 5) NOP 2615 — both an (f)(1) immediate and an (f)(2) change notification.
        try:
            from certifications.models import OrganicSystemPlan, OSPChangeNotification

            osp = (
                OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
            )
            if osp is not None:
                OSPChangeNotification.objects.get_or_create(
                    osp=osp,
                    change_category=OSPChangeNotification.CATEGORY_ACREAGE_FIELD_ADDITION,
                    description="Added a new 8-acre avocado block to the certified organic acreage.",
                    defaults=dict(
                        date_notified=date(2025, 11, 3),
                        method=OSPChangeNotification.METHOD_WRITTEN,
                        documentation_timing=OSPChangeNotification.DOC_AT_NOTIFICATION,
                    ),
                )
                OSPChangeNotification.objects.get_or_create(
                    osp=osp,
                    change_category=OSPChangeNotification.CATEGORY_PROHIBITED_SUBSTANCE,
                    description="Neighboring conventional grove sprayed herbicide; wind drift onto the north buffer reported same day.",
                    defaults=dict(
                        date_notified=date(2026, 1, 18),
                        method=OSPChangeNotification.METHOD_VERBAL,
                    ),
                )
                self.stdout.write(f"  NOP 2615 change notifications on OSP #{osp.id}: {osp.change_notifications.count()} total.")
            else:
                self.stdout.write(self.style.WARNING("  No OSP found — skipped NOP 2615 change notifications."))
        except Exception as e:  # noqa: BLE001 — non-fatal enrichment
            self.stdout.write(self.style.WARNING(f"  NOP 2615 notifications skipped: {e}"))

        try:
            prod.update_trust_metrics()
        except Exception as e:  # noqa: BLE001 — non-fatal
            self.stdout.write(self.style.WARNING(f"  Trust metrics update failed (non-fatal): {e}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Solana Verde demo audit fields backfilled (all sections)."))
