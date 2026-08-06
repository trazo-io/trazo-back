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

# Internally consistent with the fixture: harvest yield is ~5,080 kg to
# Pacific Organic Distributors (POD) — the buyer named in the OSP/transport
# narrative. Two post-harvest deliveries totaling ≤ yield, dated AFTER the
# 2026-04-10 harvest, in the SAME unit (kg) as the yield so the mass-balance
# reconciles cleanly.
SOLANA_SALES = [
    {
        "buyer_name": "Pacific Organic Distributors (POD)",
        "sale_date": date(2026, 4, 16),
        "quantity": Decimal("3000.00"),
        "quantity_unit": "kg",
        "invoice_number": "SV-INV-2026-0112",
        "organic_on_invoice": True,
    },
    {
        "buyer_name": "Pacific Organic Distributors (POD)",
        "sale_date": date(2026, 4, 22),
        "quantity": Decimal("1800.00"),
        "quantity_unit": "kg",
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
            self.stderr.write(
                self.style.ERROR(f"No '{COMPANY_NAME}' company found. Run create_organic_pilot_farm first.")
            )
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

        # 0) REPAIR prior inconsistent demo data (idempotent):
        #    (a) A raw manure event wrongly reclassified processed_5006 while still
        #        carrying a raw 90/120 interval — revert it to raw.
        reverted = 0
        for ev in prod.history_soilmanagementevent_events.filter(
            manure_treatment="processed_5006", manure_harvest_interval__in=["90", "120"]
        ):
            ev.manure_treatment = None
            ev.processed_manure_temp_f = None
            ev.processed_manure_attestation = None
            ev.save(update_fields=["manure_treatment", "processed_manure_temp_f", "processed_manure_attestation"])
            reverted += 1
        #    (b) Raw manure falsely labeled "OMRI-listed" — manure is an allowed
        #        input with the interval, not an OMRI product.
        relabeled = 0
        for ev in prod.history_soilmanagementevent_events.filter(
            amendment_type__icontains="manure", amendment_organic_approved="omri_listed"
        ):
            ev.amendment_organic_approved = "yes"
            ev.save(update_fields=["amendment_organic_approved"])
            relabeled += 1
        if reverted or relabeled:
            self.stdout.write(f"  Repaired: {reverted} manure reclassification(s), {relabeled} false OMRI label(s).")

        #    (c) Stale citation: "organic on invoice" is the audit-trail disclosure
        #        provision § 205.103(b)(2), NOT § 205.301(f) (product composition).
        #        Scrub existing event notes + OSP narrative seeded before the source fix.
        def _scrub(obj):
            if isinstance(obj, str):
                return obj.replace("§ 205.301(f)", "§ 205.103(b)(2)").replace("205.301(f)", "205.103(b)(2)")
            if isinstance(obj, dict):
                return {k: _scrub(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_scrub(v) for v in obj]
            return obj

        cite_fixed = 0
        from history.models import BusinessEvent, GeneralEvent

        for model in (BusinessEvent, GeneralEvent):
            for ev in model.objects.filter(history=prod, observation__contains="205.301(f)"):
                ev.observation = _scrub(ev.observation)
                ev.save(update_fields=["observation"])
                cite_fixed += 1
        try:
            from certifications.models import OrganicSystemPlan

            osp0 = OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
            if osp0 and isinstance(osp0.sections, dict) and "205.301(f)" in str(osp0.sections):
                osp0.sections = _scrub(osp0.sections)
                osp0.save(update_fields=["sections"])
                cite_fixed += 1
        except Exception:  # noqa: BLE001 — non-fatal
            pass
        if cite_fixed:
            self.stdout.write(f"  Fixed {cite_fixed} stale § 205.301(f) citation(s).")

        # 1) NOP 5006 — add a SEPARATE, documented processed-manure event.
        # IMPORTANT: never reclassify an existing RAW manure event (e.g., the
        # fixture's aged horse manure) as processed — that produces a
        # self-contradictory record (raw-interval flag AND processed-exempt) that
        # reads to a certifier as reclassifying to dodge a flag. Create a distinct,
        # authentic event (OMRI heat-processed poultry pellets) with NO raw interval.
        soil, _created = SoilManagementEvent.objects.get_or_create(
            history=prod,
            type=SoilManagementEvent.ORGANIC_MATTER,
            manure_treatment="processed_5006",
            defaults=dict(
                created_by=user,
                description="OMRI-listed heat-processed poultry-manure pellets applied to tree rows (pathogen-reduced).",
                date=timezone.now(),
                manure_application_date=date(2025, 12, 1),
                manure_harvest_interval="na",  # interval-exempt; NOT a raw 90/120 event
                processed_manure_temp_f=Decimal("155.0"),
                processed_manure_attestation="OMRI-listed heat-processed poultry pellets (PFRP), supplier COA on file",
            ),
        )
        self.stdout.write(f"  NOP 5006 processed-manure event #{soil.id} ({'created' if _created else 'present'}).")

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

        # 4) SOE — itemized sales records. update_or_create so a prior run's
        # inconsistent rows (wrong buyer/unit/quantity) are CORRECTED, not left.
        keep_invoices = {s["invoice_number"] for s in SOLANA_SALES}
        # Drop any earlier demo sales that no longer belong (e.g., the old
        # Del Rey / Mission rows in lb that exceeded yield).
        prod.sales_records.exclude(invoice_number__in=keep_invoices).delete()
        for s in SOLANA_SALES:
            SalesRecord.objects.update_or_create(
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

            osp = OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
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
                self.stdout.write(
                    f"  NOP 2615 change notifications on OSP #{osp.id}: {osp.change_notifications.count()} total."
                )
            else:
                self.stdout.write(self.style.WARNING("  No OSP found — skipped NOP 2615 change notifications."))
        except Exception as e:  # noqa: BLE001 — non-fatal enrichment
            self.stdout.write(self.style.WARNING(f"  NOP 2615 notifications skipped: {e}"))

        # Scrub the legacy "Transparency score target: 95%+" phrase from any event
        # note — an engagement metric is irrelevant to a certifier audit and reads
        # oddly in the export. Idempotent; safe on already-clean data.
        scrubbed = 0
        for ev in prod.history_generalevent_events.filter(observation__icontains="Transparency score target"):
            ev.observation = (
                "Successful organic season. Events documented across all 7 categories; "
                "records compiled into the POD buyer package and organic documentation export."
            )
            ev.save(update_fields=["observation"])
            scrubbed += 1
        self.stdout.write(f"  Scrubbed transparency-score note from {scrubbed} event(s).")

        try:
            prod.update_trust_metrics()
        except Exception as e:  # noqa: BLE001 — non-fatal
            self.stdout.write(self.style.WARNING(f"  Trust metrics update failed (non-fatal): {e}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Solana Verde demo audit fields backfilled (all sections)."))
