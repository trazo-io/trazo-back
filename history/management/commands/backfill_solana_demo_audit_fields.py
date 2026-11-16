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

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from company.models import Company
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    Production,
    ProductionEvent,
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)
from users.models import User

from ._solana_verde_base import BUYER_NAME, COMPANY_NAME, SEASON_SOLD_KG, SEASON_YIELD_KG

# One row per TRUCKLOAD, not per season. 260,000 kg of sold fruit is ~14 refrigerated
# loads at ~41,000 lb each; a single sales row for the whole season would put 286 short
# tons on one bill of lading, which is the first thing a certifier would question.
#
# Every load carries the transport block CCOF's grower inspection checklist asks for:
#   "Cleaning logs: Are records available to confirm clean out for production equipment
#    ... and crop harvest & transport equipment?"
# and the § 205.301 labeling category their SOE guidance requires on audit-trail
# documents ("products must be identified as organic on external audit trail documents").
#
# The fleet is deliberately mixed. Dedicated organic trailers need no cleaning and have no
# prior load to declare; hired reefers do, and their prior commodity is NAMED — that line
# is what lets an inspector judge contamination risk. `prior_products_transported` stays
# BLANK on dedicated units because blank means "not documented / not applicable", never
# "nothing was carried".
_DEDICATED = {
    "carrier_name": "Cool-Chain Logistics",
    "clean_transport_method": "dedicated_organic",
    "transport_cleaning_method": "not_required",
    "prior_products_transported": "",
    "transport_inspected_free_of": ["foreign_odors", "residues", "conventional_products"],
}
_HIRED_WASHED = {
    "carrier_name": "Valley Reefer Lines",
    "clean_transport_method": "inspected",
    "transport_cleaning_method": "washed",
    "prior_products_transported": "Conventional Hass avocados (immediately prior load)",
    "transport_inspected_free_of": ["foreign_odors", "residues", "conventional_products"],
}
_HIRED_AFFIDAVIT = {
    "carrier_name": "Valley Reefer Lines",
    "clean_transport_method": "affidavit",
    "transport_cleaning_method": "swept",
    "prior_products_transported": "Conventional navel oranges (immediately prior load)",
    "transport_inspected_free_of": ["residues", "conventional_products"],
}

# (day-of-load, kg). Sums to SEASON_SOLD_KG exactly — asserted below, because a mass
# balance that silently stops reconciling is the failure this whole fixture exists to
# demonstrate the absence of.
_LOADS = [
    ((4, 15), 18600, _DEDICATED),
    ((4, 17), 19100, _HIRED_WASHED),
    ((4, 20), 18200, _DEDICATED),
    ((4, 22), 19400, _HIRED_AFFIDAVIT),
    ((4, 24), 18800, _DEDICATED),
    ((4, 27), 17900, _HIRED_WASHED),
    ((4, 29), 19000, _DEDICATED),
    ((5, 1), 18500, _HIRED_WASHED),
    ((5, 4), 18300, _DEDICATED),
    ((5, 6), 19200, _HIRED_AFFIDAVIT),
    ((5, 8), 18700, _DEDICATED),
    ((5, 11), 18100, _HIRED_WASHED),
    ((5, 13), 18900, _DEDICATED),
    ((5, 15), 17300, _HIRED_WASHED),
]

SOLANA_SALES = []
for _i, ((_m, _d), _kg, _transport) in enumerate(_LOADS):
    SOLANA_SALES.append(
        {
            "buyer_name": BUYER_NAME,
            "sale_date": date(2026, _m, _d),
            "quantity": Decimal(_kg),
            "quantity_unit": "kg",
            # Load 1 reuses the invoice and BOL already named in the shipping
            # BusinessEvent narrative, so the event and the sales row cross-reference
            # each other instead of describing two unrelated shipments.
            "invoice_number": f"SVR-INV-2026-{41 + _i:03d}",
            "bill_of_lading": ("BOL-POD-2026-04-15-007" if _i == 0 else f"BOL-POD-2026-{_m:02d}-{_d:02d}-{_i + 7:03d}"),
            "vehicle_id": "CCL-2814" if _i == 0 else f"{'CCL' if _transport is _DEDICATED else 'VRL'}-{2814 + _i}",
            "destination": "POD Distribution Hub, 5005 NE Portland Hwy, Portland, OR 97218",
            "organic_on_invoice": True,
            # Raw, unprocessed fruit with no added ingredients — § 205.301(a).
            "organic_label_category": "100_percent_organic",
            **_transport,
        }
    )

assert sum(s["quantity"] for s in SOLANA_SALES) == SEASON_SOLD_KG, "demo loads must sum to the season sold quantity"
assert SEASON_SOLD_KG <= SEASON_YIELD_KG, "cannot sell more than was harvested"


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
            Production.objects.filter(parcel__establishment__company=company, published=True)
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
            defaults = {k: v for k, v in s.items() if k != "invoice_number"}
            SalesRecord.objects.update_or_create(
                production=prod,
                invoice_number=s["invoice_number"],
                defaults=defaults,
            )
        self.stdout.write(f"  SOE sales records: {prod.sales_records.count()} total.")

        # 4b) Keep the LEGACY single-shipment fields on History in step with the itemized
        # rows above. They are a second, older statement of the same facts and the packet
        # prints both: before this, History said 5,080 kg sold while the SalesRecords said
        # 260,000 kg, and History named a different buyer than every sales row.
        prod.production_amount = float(SEASON_YIELD_KG)
        prod.production_unit = "kg"
        prod.quantity_sold = SEASON_SOLD_KG
        prod.quantity_sold_unit = "kg"
        prod.sold_to = BUYER_NAME
        prod.organic_on_invoice = True
        prod.organic_label_category = "100_percent_organic"
        prod.save(
            update_fields=[
                "production_amount",
                "production_unit",
                "quantity_sold",
                "quantity_sold_unit",
                "sold_to",
                "organic_on_invoice",
                "organic_label_category",
            ]
        )

        # 4c) Narratives written before the yield correction. An event that SAYS
        # "Total yield: 11,200 lbs" beside a `yield_quantity` of 275,000 kg is the
        # discrepancy CCOF's Production Verification Audit opens on, and no structural
        # check catches it because prose is not a field.
        stale_numbers = {
            "11,200 lbs (5,080 kg)": "606,270 lbs (275,000 kg)",
            "Total yield 11,200 lbs (5,080 kg)": "Total yield 606,270 lbs (275,000 kg)",
            "approximately 11,200 lbs": "approximately 590,000 lbs",
            "~11,200 lbs": "~590,000 lbs",
            "12,000 to 11,200 lbs": "650,000 to 590,000 lbs",
            "Estimated 1,200 lbs of fruit removed": "Estimated 65,000 lbs of fruit removed",
            "Yield 5,080 kg total": "Yield 275,000 kg total",
            "448 cartons (5,080 kg, 11,200 lbs net)": "1,640 cartons (18,600 kg, 41,006 lbs net)",
            "Total packed: 448 cartons": "Season total packed: 24,250 cartons",
            "All 448 cartons": "All 1,640 cartons",
            "Organically Grown Company (OGC)": BUYER_NAME,
        }

        def _renumber(text):
            for old, new in stale_numbers.items():
                text = text.replace(old, new)
            return text

        narrative_fixed = 0
        for model in (ProductionEvent, BusinessEvent, GeneralEvent, WeatherEvent):
            for ev in model.objects.filter(history=prod):
                changed = []
                for field in ("description", "observation"):
                    value = getattr(ev, field, None)
                    if isinstance(value, str) and value:
                        fixed = _renumber(value)
                        if fixed != value:
                            setattr(ev, field, fixed)
                            changed.append(field)
                if isinstance(ev.extra_data, dict):
                    patched = dict(ev.extra_data)
                    for key, old_value, new_value in (
                        ("yield_revision_lbs", 11200, 590000),
                        ("remaining_yield_lbs_est", 11200, 590000),
                        ("cartons_packed", 448, 24250),
                        ("cartons_shipped", 448, 1640),
                        ("net_weight_kg", 5080, 18600),
                        ("net_weight_lbs", 11200, 41006),
                    ):
                        if patched.get(key) == old_value:
                            patched[key] = new_value
                    if patched.get("buyer_name") == "Organically Grown Company (OGC)":
                        patched["buyer_name"] = BUYER_NAME
                    if patched != ev.extra_data:
                        ev.extra_data = patched
                        changed.append("extra_data")
                if changed:
                    ev.save(update_fields=changed)
                    narrative_fixed += 1
        self.stdout.write(f"  Yield narratives realigned on {narrative_fixed} event(s).")

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

        # LAST — clear the fixture's edit log. Every LogEntry on this production was written
        # by a seeder or by this command, never by an operator, but the packet reports them as
        # "N edit(s) recorded after production was finalized. Inspector should review these
        # changes" — an integrity warning about the act of building the demo. On a packet shown
        # to a certifier that is worse than noise: it invites a question about record tampering
        # that has no answer, because nothing was tampered with.
        #
        # Runs last so this command's own writes are included. HARD-SCOPED to the DEMO
        # fixture: this must never touch a real operation's audit trail, which is evidence.
        if "(DEMO)" not in establishment.name:
            raise CommandError(f"Refusing to clear audit history for non-demo establishment {establishment.name!r}.")
        try:
            from auditlog.models import LogEntry

            targets = [prod]
            for qs in (
                prod.history_productionevent_events.all(),
                prod.history_chemicalevent_events.all(),
                prod.history_soilmanagementevent_events.all(),
                prod.history_pestmanagementevent_events.all(),
                prod.history_businessevent_events.all(),
                prod.history_weatherevent_events.all(),
                prod.history_generalevent_events.all(),
            ):
                targets.extend(qs)
            cleared = 0
            for obj in targets:
                cleared += LogEntry.objects.get_for_object(obj).delete()[0]
            self.stdout.write(f"  Cleared {cleared} seeder-generated audit-log entr(ies) on the DEMO fixture.")
        except ImportError:  # pragma: no cover — auditlog is a hard dependency in practice
            self.stdout.write(self.style.WARNING("  auditlog not installed; skipped edit-log reset."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Solana Verde demo audit fields backfilled (all sections)."))
