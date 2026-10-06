"""
Regression tests for commercially sensitive field leakage in PublicHistorySerializer.

The public consumer QR endpoint (/public_history/) must NOT expose vendor identity,
purchase invoices, or purchase dates to anyone scanning a product QR code. These
fields are NOP traceability data (7 CFR 205.103) but are competitive intelligence
that farmers do not consent to publishing.

The codebase already documents this policy via _sanitize_extra_data_for_public()
which blocks the key "supplier" in extra_data (history/serializers.py BLOCKED_KEYS).
This test enforces the equivalent policy for top-level model fields hand-rolled
into PublicHistorySerializer.get_events(). See AUDIT_INSTRUCTIONS Standard Fix #5.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from company.models import Company, Establishment
from history.models import BusinessEvent, ChemicalEvent, GeneralEvent, History, ProductionEvent, SoilManagementEvent
from history.serializers import PublicHistorySerializer
from product.models import Parcel, Product
from users.models import User, WorksIn

# Top-level model fields on ChemicalEvent that are commercially sensitive and
# MUST NEVER appear in the public consumer event payload.
SENSITIVE_CHEMICAL_KEYS = frozenset(
    [
        "supplier_name",
        "purchase_date",
        "purchase_invoice",
        "quantity_purchased",
        "quantity_purchased_unit",
    ]
)

# Top-level model fields on ProductionEvent (PL/planting subtype) that are
# commercially sensitive seed vendor/purchase records (7 CFR 205.204 / NOP 5029).
# Same class as SENSITIVE_CHEMICAL_KEYS: they belong only on the certifier-facing
# NOP PDF, never on the public QR page. seed_lot_number / seed_certification_status
# / seed_treatment are legitimate consumer transparency and intentionally excluded
# from this set.
SENSITIVE_PRODUCTION_KEYS = frozenset(
    [
        "seed_supplier_name",
        "seed_purchase_date",
        "seed_purchase_invoice",
        "seed_search_attempts",
    ]
)

# NOP-technical / worker-safety / self-graded event fields that are certifier-only and
# MUST NOT appear on the public consumer payload (2026-06 NOP-alignment audit, B0/B1).
# REI/PHI/RUP/EPA-reg/CA-DPR protect FARM WORKERS or are enforcement identifiers that
# falsely imply a CONSUMER hazard; concentration/volume/NPK/buffer/is_fertigation are
# agronomic audit data; applicator_name is also a worker-name PII exposure.
# (verification_level is deliberately NOT here — it is a factual documentation tier coupled
# to the photo-evidence display. `transparency_score` is not here either any more: it left
# every payload on 2026-09-30, so there is nothing to strip. See
# history/tests/test_no_transparency_score_served.py.)
# Every one of these remains in the certifier-facing NOP PDF (audit_export_service reads
# the event models directly), so stripping them here costs zero certifier coverage.
NOP_TECHNICAL_EVENT_KEYS = frozenset(
    [
        "rei_hours",
        "phi_days",
        "restricted_use_pesticide",
        "epa_registration_number",
        "ca_dpr_permit_number",
        "ca_dpr_permit_county",
        "ca_dpr_permit_expires",
        "applicator_name",
        "applicator_certification",
        "concentration",
        "volume",
        "volume_unit",
        "nitrogen_percentage",
        "phosphorus_percentage",
        "potassium_percentage",
        "is_fertigation",
        "buffer_zone_meters",
    ]
)

# Sensitive keys that can ride in the free-form ``extra_data`` JSON blob and were confirmed
# leaking live on the public QR endpoint (2026-06 consumer-page audit): wholesale buyer
# identity, pricing/margin, commercial documents, logistics, supplier identities, and
# inspection/audit findings. _sanitize_extra_data_for_public() must strip every one.
SENSITIVE_EXTRA_DATA_KEYS = frozenset(
    [
        "buyer_name",
        "buyer_address",
        "invoice_number",
        "purchase_order",
        "bill_of_lading",
        "total_cost",
        "cost_per_1000_eggs",
        "premium_pct",
        "manure_source",
        "compost_source",
        "conventional_operator",
        "carrier",
        "trailer_number",
        "destination",
        "inspector",
        "audit_date",
        "major_nonconformances",
        "minor_observations",
        # Aliases that leaked past the old deny-list under different names and that the
        # allow-list flip must also block (2026-06 audit, 98-history scan):
        "auditor",
        "audit_score",
        "inspected_by",
        "major_nc",
        "minor_nc",
        "cost_vs_conventional",
        "hive_rental_per_colony",
        "pollination_services_value",
        "premium_market_percentage",
        "nursery",
        "bee_source",
        "processor",
        "lab_name",
        "original_extra_data",
        "ui_form_data",
        # An entirely novel key the allow-list has never seen — must default-deny:
        "some_future_sensitive_key_xyz",
    ]
)

# Legitimate agronomic / consumer-transparency keys that live in extra_data and MUST survive
# sanitization. Guards against an over-broad deny-list regressing real transparency content.
SAFE_EXTRA_DATA_KEYS = frozenset(
    [
        "rootstock",
        "composted",
        "compost_age_months",
        "thrips_per_leaf_avg",
        "soil_moisture_vwc_pct",
        "lot_id",
    ]
)


class PublicSerializerSupplierLeakageTests(TestCase):
    """Regression: supplier chain must never leak to the public QR endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(email="leak@test.com", password="x")
        self.company = Company.objects.create(name="Leak Farm")
        self.establishment = Establishment.objects.create(name="L1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="LP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Leak Test Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # Chemical event with full supplier chain populated. If any of these
        # values appear in the public payload, the test fails.
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            commercial_name="Bordeaux Mix",
            supplier_name="Hydra-Gardens Inc.",
            purchase_date=date(2026, 4, 15),
            purchase_invoice="INV-HG-2026-0142",
            quantity_purchased=25,
            quantity_purchased_unit="kg",
            date=timezone.now(),
        )

    def _public_chemical_event(self):
        """Serialize and return the first chemical event dict from the public payload."""
        data = PublicHistorySerializer(self.history).data
        events = data.get("events") or []
        chem = [e for e in events if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1, "expected exactly one chemical event in public payload")
        return chem[0]

    def test_no_sensitive_keys_present(self):
        """Sensitive supplier-chain keys must be absent from the public chemical event dict."""
        event = self._public_chemical_event()
        leaked = SENSITIVE_CHEMICAL_KEYS.intersection(event.keys())
        self.assertEqual(
            leaked,
            set(),
            f"Public consumer endpoint leaked commercially sensitive keys: {sorted(leaked)}. "
            f"These fields belong only on the certifier-facing NOP PDF, not the QR page.",
        )

    def test_sensitive_values_not_in_serialized_blob(self):
        """Defense in depth: raw vendor/invoice strings must not appear anywhere in the payload."""
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("Hydra-Gardens Inc.", blob, "supplier_name leaked into public payload")
        self.assertNotIn("INV-HG-2026-0142", blob, "purchase_invoice leaked into public payload")

    def test_non_sensitive_chemical_fields_still_present(self):
        """Sanity check: stripping sensitive keys must not regress legitimate consumer fields."""
        event = self._public_chemical_event()
        # commercial_name is consumer-facing transparency (what was applied) — must remain.
        self.assertEqual(event.get("commercial_name"), "Bordeaux Mix")
        # Standard event metadata must remain.
        self.assertEqual(event.get("type"), "chemical")


class PublicSerializerBusinessCarbonCreditsGatingTests(TestCase):
    """Carbon credits must not reach a shopper AT ALL (2026-08-18).

    This class used to enforce a GATE: the unit was allowed on the public wire when a real
    earned amount was present, and suppressed when it was null or zero — the concern then was
    an orphan "Carbon Credits Unit: tCO2e" card left behind by the model default.

    The activity type has since been withdrawn (see BUSINESS_ACTIVITY_CHOICES). A traded-credit
    figure is a tradeable-offset claim, and Trazo measures direct operational emissions with
    EPA/USDA factors — not the credit-grade accounting such a figure asserts. That is the
    self-created sustainability claim EU ECGT 2024/825 (live 2026-09-27) reaches, and an
    unsubstantiated benefit claim under FTC 16 CFR 260.6.

    So the assertion inverts: not "surfaces only when legitimate" but "never surfaces". The
    columns still exist and historical rows keep their values; the shopper does not see them.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="bizleak@test.com", password="x")
        self.company = Company.objects.create(name="Biz Leak Farm")
        self.establishment = Establishment.objects.create(name="B1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="BP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = History.objects.create(
            name="Biz Leak Test Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _public_business_events(self):
        data = PublicHistorySerializer(self.history).data
        events = data.get("events") or []
        return [e for e in events if e.get("type") == "business"]

    def test_orphan_unit_dropped_when_no_credits_earned(self):
        """Certification event with legacy carbon_credits_unit but no earned amount: unit must be None."""
        BusinessEvent.objects.create(
            history=self.history,
            type=BusinessEvent.CERTIFICATION,
            business_type="certification",
            certification_type="organic_usda",
            certificate_number="USDA-2026-0001",
            carbon_credits_earned=None,
            carbon_credits_unit="tCO2e",  # legacy default still on the row
            date=timezone.now(),
        )
        events = self._public_business_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIsNone(
            ev.get("carbon_credits_earned"),
            "earned should be None on a certification event",
        )
        self.assertIsNone(
            ev.get("carbon_credits_unit"),
            "unit must be gated on truthy earned amount; legacy 'tCO2e' default leaked",
        )

    def test_a_historical_credits_row_still_shows_a_shopper_nothing(self):
        """The inverted case. A row written before the withdrawal keeps its stored amount —
        and the public payload must carry neither the figure nor its unit."""
        BusinessEvent.objects.create(
            history=self.history,
            type=BusinessEvent.CERTIFICATION,
            # Written directly: 'carbon_credits' is no longer in BUSINESS_ACTIVITY_CHOICES, so
            # no serializer would accept it today. That is the point — the row predates the
            # withdrawal, and the wire must still be clean.
            business_type="carbon_credits",
            carbon_credits_earned=5.0,
            carbon_credits_unit="tCO2e",
            date=timezone.now(),
        )
        events = self._public_business_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertNotIn("carbon_credits_earned", ev, "a credit figure reached a shopper")
        self.assertNotIn("carbon_credits_unit", ev, "a credit unit reached a shopper")

    def test_the_activity_type_can_no_longer_be_chosen(self):
        """Guards the removal itself: without this, re-adding the choice breaks nothing."""
        from history.models import BusinessEvent as _BE

        self.assertNotIn(
            "carbon_credits",
            [c[0] for c in _BE.BUSINESS_ACTIVITY_CHOICES],
            "carbon_credits was re-added as a loggable business activity",
        )

    def test_unit_dropped_when_credits_zero(self):
        """Edge case: explicit zero earned amount must drop unit (not just null)."""
        BusinessEvent.objects.create(
            history=self.history,
            type=BusinessEvent.CERTIFICATION,
            business_type="certification",
            carbon_credits_earned=0,
            carbon_credits_unit="tCO2e",
            date=timezone.now(),
        )
        events = self._public_business_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        # `assertNotIn`, not `assertIsNone`: the keys are gone from the payload, and a
        # .get() returning None cannot tell "absent" from "present and null".
        self.assertNotIn("carbon_credits_earned", ev)
        self.assertNotIn("carbon_credits_unit", ev)


class PublicSerializerSeedSupplierLeakageTests(TestCase):
    """Regression: seed vendor/purchase chain must never leak to the public QR endpoint.

    Parallel to PublicSerializerSupplierLeakageTests for chemical events. A shopper
    expanding a Planting card must not see the farm's nursery name, the seed invoice
    number, the purchase date, or the NOP 5029 commercial-availability search log
    (which records the names of suppliers the farmer contacted). These are 7 CFR
    205.204 / NOP 5029 traceability records — competitive intelligence farmers do not
    consent to publishing. Legitimate seed transparency (lot number, certification
    status, treatment) MUST remain. See AUDIT_INSTRUCTIONS Standard Fix #5.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="seedleak@test.com", password="x")
        self.company = Company.objects.create(name="Seed Leak Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="SP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = History.objects.create(
            name="Seed Leak Test Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # Planting event with the full seed vendor/purchase chain populated. If any of
        # these values appears in the public payload, the test fails. seed_search_attempts
        # carries a contacted-supplier identity to prove the NOP 5029 log is also stripped.
        ProductionEvent.objects.create(
            history=self.history,
            type=ProductionEvent.PLANTING,
            seed_supplier_name="Brokaw Nursery, Saticoy CA",
            seed_purchase_date=date(2025, 11, 20),
            seed_purchase_invoice="BN-2025-11-4871",
            seed_search_attempts=[{"supplier": "Willits & Newcomb Inc.", "result": "unavailable"}],
            seed_lot_number="LOT-HASS-2025-09",
            seed_certification_status="organic",
            seed_treatment="untreated",
            date=timezone.now(),
        )

    def _public_planting_event(self):
        """Serialize and return the planting event dict from the public payload."""
        data = PublicHistorySerializer(self.history).data
        events = data.get("events") or []
        planting = [e for e in events if e.get("type") == "PL"]
        self.assertEqual(len(planting), 1, "expected exactly one PL event in public payload")
        return planting[0]

    def test_no_sensitive_seed_keys_present(self):
        """Sensitive seed vendor/purchase keys must be absent from the public planting dict."""
        event = self._public_planting_event()
        leaked = SENSITIVE_PRODUCTION_KEYS.intersection(event.keys())
        self.assertEqual(
            leaked,
            set(),
            f"Public consumer endpoint leaked commercially sensitive seed keys: {sorted(leaked)}. "
            f"These fields belong only on the certifier-facing NOP PDF, not the QR page.",
        )

    def test_seed_vendor_values_not_in_serialized_blob(self):
        """Defense in depth: raw nursery/invoice/contacted-supplier strings must not appear anywhere."""
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("Brokaw Nursery, Saticoy CA", blob, "seed_supplier_name leaked into public payload")
        self.assertNotIn("BN-2025-11-4871", blob, "seed_purchase_invoice leaked into public payload")
        self.assertNotIn("Willits & Newcomb Inc.", blob, "seed_search_attempts supplier identity leaked")

    def test_storage_facility_identifiers_not_public(self):
        """storage_location / storage_temperature_f are FSMA-204/certifier data.

        Sprint 3.2 put them on the anonymous wire "for cold-chain transparency", but no
        consumer component ever rendered them (the event registry gives them no consumer
        surface) — internal facility identifiers ("Warehouse B-Bin-12") rode the public
        payload for nothing. Removed 2026-08-09; they stay owner/certifier-side.
        """
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn('"storage_location"', blob, "storage_location key on the public wire")
        self.assertNotIn('"storage_temperature_f"', blob, "storage_temperature_f key on the public wire")

    def test_legitimate_seed_fields_still_present(self):
        """Sanity: stripping vendor data must not regress legitimate seed transparency.

        What was PLANTED stays public. `seed_certification_status` left this list on
        2026-08-15 — see test_self_assigned_certification_status_is_not_public below.
        """
        event = self._public_planting_event()
        self.assertEqual(event.get("seed_treatment"), "untreated")

    def test_self_assigned_certification_status_is_not_public(self):
        """A grower dropdown of CERTIFICATION statuses must not ride the anonymous wire.

        `seed_certification_status` is operator-entered and its values are certification
        statuses ("Certified Organic"). Published anonymously with no self-reported qualifier
        it is a self-assigned certification-mark claim — the same class as the 2026-08-09 OMRI
        incident, and the same reason this file's sibling field `seed_treatment_allowed_basis`
        (value `omri_listed`) has never been public.

        The certified fact a shopper can rely on is the farm's third-party certification,
        published from structured USDA-OID-matched records by transparency_views.
        """
        event = self._public_planting_event()
        self.assertNotIn("seed_certification_status", event)

    def test_operator_only_keys_are_off_the_public_wire(self):
        """Keys that ship publicly but no consumer component renders.

        Added 2026-08-15 after a live capture of the anonymous endpoint. Each of these was on
        the wire with NO `consumer_card` surface in the event registry, i.e. scrapable JSON and
        nothing else — the same finding, and the same fix, as storage_location above.

          seed_lot_number        a SUPPLIER's batch id ("BN-HASS-2025-L047")
          block_id               an internal operator id ("Hillside Grove A - East Buffer Zone")
          growth_stage           no consumer surface
          production_efficiency  a SELF-GRADED rating the registry withholds from the card on
          operation_efficiency   stated ECGT/FTC grounds — and it shipped under two names
        """
        event = self._public_planting_event()
        for key in (
            "seed_lot_number",
            "block_id",
            "growth_stage",
            "production_efficiency",
            "operation_efficiency",
        ):
            self.assertNotIn(
                key,
                event,
                f"{key} is on the anonymous wire with no consumer renderer behind it",
            )

    def test_vendor_name_does_not_leak_through_free_text(self):
        """The stripped field is not the only way a vendor reaches the page.

        🔴 Measured live 2026-08-15 on the demo farm: `seed_supplier_name` was correctly
        stripped, and the same nursery was published verbatim inside `description` —
        "...nursery stock from Saticoy Grove Nursery for replanting 28 trees...". The existing
        assertion above passed the whole time because it matched the FULL stored string,
        "Brokaw Nursery, Saticoy CA", while the prose named the vendor without the city.

        So assert on the distinctive vendor token, not the exact stored value.
        """
        import json

        event = ProductionEvent.objects.filter(history=self.history, type="PL").first()
        event.description = "Received stock from Brokaw Nursery for the east block replant."
        event.save(update_fields=["description"])

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn(
            "Brokaw",
            blob,
            "the seed vendor reached the anonymous payload through free text — stripping "
            "seed_supplier_name is not enough if description/observation are unscrubbed",
        )


class PublicSerializerExtraDataLeakageTests(TestCase):
    """Regression: the free-form extra_data JSON blob must not leak commercial/PII/audit data.

    The public QR endpoint was confirmed (2026-06 audit) leaking wholesale buyer identity,
    pricing/margin, invoice/PO/BOL numbers, logistics, supplier identities, and inspection
    nonconformance findings through extra_data — none of which a grocery shopper should see
    and all of which is competitive intelligence. _sanitize_extra_data_for_public() must
    strip them while preserving legitimate agronomic transparency keys.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="extraleak@test.com", password="x")
        self.company = Company.objects.create(name="Extra Leak Farm")
        self.establishment = Establishment.objects.create(name="X1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="XP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = History.objects.create(
            name="Extra Data Leak Test Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # A production event whose extra_data mixes sensitive commercial/PII data with
        # legitimate agronomic transparency. Values mirror the live fixture that leaked.
        ProductionEvent.objects.create(
            history=self.history,
            type=ProductionEvent.HARVESTING,
            extra_data={
                # Sensitive — must be stripped
                "buyer_name": "Organically Grown Company (OGC)",
                "buyer_address": "1800 Prairie Rd, Eugene, OR 97402",
                "invoice_number": "SVR-INV-2026-041",
                "purchase_order": "OGC-PO-2026-0412",
                "bill_of_lading": "BOL-OGC-2026-04-15-007",
                "total_cost": 3612,
                "cost_per_1000_eggs": 0.85,
                "premium_pct": 72,
                "manure_source": "Valley Stables, Fallbrook CA",
                "compost_source": "On-farm",
                "conventional_operator": "Rodriguez Ranch (conventional citrus)",
                "carrier": "Cool-Chain Logistics",
                "trailer_number": "CCL-2814",
                "destination": "OGC Distribution Hub, Portland, OR",
                "inspector": "Sarah Chen (CCOF)",
                "audit_date": "2026-03-28",
                "major_nonconformances": 0,
                "minor_observations": 1,
                # Alias variants that aliased past the old deny-list:
                "auditor": "Sarah Chen",
                "audit_score": 98,
                "inspected_by": "M. Torres",
                "major_nc": 0,
                "minor_nc": 1,
                "cost_vs_conventional": "-12%",
                "hive_rental_per_colony": 185,
                "pollination_services_value": 4200,
                "premium_market_percentage": 72,
                "nursery": "Brokaw Nursery",
                "bee_source": "Olson Apiaries",
                "processor": "Central Valley Packing Co.",
                "lab_name": "AgriLab Analytics Inc.",
                "original_extra_data": {"buyer_name": "OGC", "total_cost": 3612},
                "ui_form_data": {"draft": True},
                # Novel key the allow-list has never seen — must be dropped by default:
                "some_future_sensitive_key_xyz": "leak me if you can",
                # Legitimate agronomic — must survive
                "rootstock": "Dusa",
                "composted": True,
                "compost_age_months": 8,
                "thrips_per_leaf_avg": 1.2,
                "soil_moisture_vwc_pct": 24,
                "lot_id": "SVR-2026-HA-001",
            },
            date=timezone.now(),
        )

    def _public_harvest_extra_data(self):
        data = PublicHistorySerializer(self.history).data
        events = data.get("events") or []
        ha = [e for e in events if e.get("type") == "HA"]
        self.assertEqual(len(ha), 1, "expected exactly one HA event in public payload")
        return ha[0].get("extra_data") or {}

    def test_no_sensitive_extra_data_keys_present(self):
        """Commercial / PII / audit keys must be absent from public extra_data."""
        ed = self._public_harvest_extra_data()
        leaked = SENSITIVE_EXTRA_DATA_KEYS.intersection(ed.keys())
        self.assertEqual(
            leaked,
            set(),
            f"Public endpoint leaked sensitive extra_data keys: {sorted(leaked)}.",
        )

    def test_sensitive_extra_data_values_not_in_blob(self):
        """Defense in depth: raw buyer/margin/invoice/inspector strings must not appear anywhere."""
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        for needle in [
            "Organically Grown Company",
            "1800 Prairie Rd",
            "SVR-INV-2026-041",
            "OGC-PO-2026-0412",
            "Cool-Chain Logistics",
            "Rodriguez Ranch",
            "Sarah Chen",
            "Olson Apiaries",
            "Central Valley Packing Co.",
            "AgriLab Analytics Inc.",
            "leak me if you can",
        ]:
            self.assertNotIn(needle, blob, f"leaked sensitive value: {needle}")

    def test_legitimate_agronomic_extra_data_survives(self):
        """Sanity: deny-list must not strip legitimate agronomic transparency keys."""
        ed = self._public_harvest_extra_data()
        for key in SAFE_EXTRA_DATA_KEYS:
            self.assertIn(key, ed, f"legitimate agronomic key wrongly stripped: {key}")
        self.assertEqual(ed.get("rootstock"), "Dusa")
        self.assertEqual(ed.get("lot_id"), "SVR-2026-HA-001")


# F20 (2026-06): legal spray-record fields — CA Pesticide Use Report (DPR-PML-017C)
# + GLOBALG.A.P. identity/operational data. These belong on the farmer dashboard and
# the certifier-facing audit/PUR export ONLY, never on the public consumer QR page.
SENSITIVE_F20_CHEMICAL_KEYS = frozenset(
    [
        "manufacturer",
        "application_start",
        "application_end",
        "planted_area",
        "planted_area_unit",
        "operator_id",
        "site_id",
        "application_county",
        "mtrs_section",
        "mtrs_township",
        "mtrs_range",
        "mtrs_base_meridian",
        "ffm_code",
    ]
)


class PublicSerializerF20LegalFieldLeakageTests(TestCase):
    """Regression: F20 legal/CA-PUR chemical fields must NOT leak to the consumer QR page."""

    def setUp(self):
        self.user = User.objects.create_user(email="f20leak@test.com", password="x")
        self.company = Company.objects.create(name="F20 Farm")
        self.establishment = Establishment.objects.create(name="F20E", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="F20P", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = History.objects.create(
            name="F20 Legal Record Test",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            manufacturer="Corteva-SECRET",
            application_start=timezone.now(),
            application_end=timezone.now(),
            planted_area="40",
            planted_area_unit="acres",
            operator_id="OIN-SECRET-37-1234",
            site_id="0001",
            application_county="Fresno",
            mtrs_section="12",
            mtrs_township="14S",
            mtrs_range="22E",
            mtrs_base_meridian="M",
            ffm_code="9999",
        )

    def _public_chemical_event(self):
        data = PublicHistorySerializer(self.history).data
        chem = [e for e in (data.get("events") or []) if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1)
        return chem[0]

    def test_f20_legal_keys_absent(self):
        event = self._public_chemical_event()
        leaked = SENSITIVE_F20_CHEMICAL_KEYS.intersection(event.keys())
        self.assertEqual(
            leaked,
            set(),
            f"Public consumer endpoint leaked F20 legal/CA-PUR fields: {sorted(leaked)}. "
            f"These are farmer/audit-export only.",
        )

    def test_f20_legal_values_not_in_blob(self):
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        for needle in ("Corteva-SECRET", "OIN-SECRET-37-1234"):
            self.assertNotIn(needle, blob, f"F20 legal value leaked into public payload: {needle}")


class PublicSerializerFPMOConsumerVisibilityTests(TestCase):
    """Regression: FP/MO practice fields SHOULD appear on the consumer QR page (transparency).

    Counterpart to the leakage tests — guards against the opposite bug (the original
    Batch-3 oversight where low_temperature / floor_management_type were dropped by
    _sanitize_extra_data_for_public because they were missing from ALLOWED_EXTRA_DATA_KEYS).
    """

    def setUp(self):
        self.user = User.objects.create_user(email="fpmo@test.com", password="x")
        self.company = Company.objects.create(name="FPMO Farm")
        self.establishment = Establishment.objects.create(name="FPMOE", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="FPMOP", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="FPMO Visibility Test",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type=ProductionEvent.FROST_PROTECTION,
            date=timezone.now(),
            area_covered=10,
            extra_data={"protection_method": "wind_machine", "low_temperature": -2.0},
        )
        ProductionEvent.objects.create(
            history=self.history,
            type=ProductionEvent.MOWING,
            date=timezone.now(),
            area_covered=10,
            extra_data={"floor_management_type": "mow"},
        )

    def _public_production_events(self):
        # Production events carry the SUBTYPE code in "type" (e.g. "FP"/"MO") and the
        # numeric event_type=1 in "event_type" — they do NOT use type=="production".
        data = PublicHistorySerializer(self.history).data
        return [e for e in (data.get("events") or []) if e.get("production_type") in ("FP", "MO")]

    def test_fpmo_practice_fields_visible(self):
        events = self._public_production_events()
        merged = {}
        for e in events:
            ed = e.get("extra_data") or {}
            merged.update(ed)
        # The Batch-3 oversight dropped these; they must survive sanitization.
        self.assertEqual(merged.get("protection_method"), "wind_machine")
        self.assertEqual(merged.get("low_temperature"), -2.0)
        self.assertEqual(merged.get("floor_management_type"), "mow")


class PublicTransparencyContactLeakageTests(TestCase):
    """Regression: the public transparency endpoint must not expose the farm's direct contact.

    A random shopper scanning a QR must not receive the producer's personal phone, email, or
    the named contact person (PII), nor the company tax/fiscal ID. The endpoint is anonymous
    (no story-vs-proof distinction server-side), so contact is withheld unconditionally; a
    wholesale buyer reaches the farm through the BuyerDocRequest form. 2026-06 audit P2-6.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="contactleak@test.com", password="x")
        self.company = Company.objects.create(
            name="Contact Leak Farm LLC",
            fiscal_id="EIN-99-7654321",
            contact_email="company@contactleak.test",
            contact_phone="+1-555-CO-LEAK",
        )
        self.establishment = Establishment.objects.create(
            name="Contact Leak Estate",
            company=self.company,
            state="CA",
            contact_person="Jane Q. Farmer",
            contact_phone="+1-555-PERSONAL",
            contact_email="jane@contactleak.test",
        )
        self.parcel = Parcel.objects.create(name="CLP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Contact Leak Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def test_no_farm_contact_in_public_transparency_payload(self):
        """The named contact person, phones, emails, and fiscal ID must be absent from the QR payload."""
        resp = self.client.get(f"/api/transparency/{self.history.public_id}/")
        self.assertEqual(resp.status_code, 200)
        blob = resp.content.decode("utf-8")
        for needle in [
            "Jane Q. Farmer",
            "+1-555-PERSONAL",
            "jane@contactleak.test",
            "company@contactleak.test",
            "+1-555-CO-LEAK",
            "EIN-99-7654321",
        ]:
            self.assertNotIn(needle, blob, f"farm contact PII leaked to public QR payload: {needle}")

    def test_farm_name_still_public(self):
        """Sanity: stripping contact must not hide the farm identity (legitimate transparency)."""
        resp = self.client.get(f"/api/transparency/{self.history.public_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Contact Leak Estate", resp.content.decode("utf-8"))


class PublicSerializerNopTechnicalLeakageTests(TestCase):
    """B0/B1 (2026-06 NOP-alignment audit): worker-safety, agronomic-audit, and
    self-graded fields must not reach the anonymous consumer QR payload, while
    legitimate consumer-transparency fields (what was applied + third-party organic
    status + the practice story) survive untouched."""

    def setUp(self):
        self.user = User.objects.create_user(email="noptech@test.com", password="x")
        self.company = Company.objects.create(name="NopTech Farm")
        self.establishment = Establishment.objects.create(name="NT1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="NTP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="NopTech Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            concentration="22.5%",
            volume=2.5,
            nitrogen_percentage=10,
            phosphorus_percentage=5,
            potassium_percentage=5,
            restricted_use_pesticide=False,
            applicator_name="Ana Torres",
            applicator_certification="CA QAL-4287",
            epa_registration_number="62719-621",
            rei_hours=Decimal("4.0"),
            phi_days=Decimal("1.0"),
            buffer_zone_meters=Decimal("8.0"),
            is_fertigation=False,
            ca_dpr_permit_number="DPR-2026-001",
            organic_approved="omri_listed",
            date=timezone.now(),
        )

    def _anon_payload(self):
        # No request context => _is_owner() is False => anonymous consumer view.
        return PublicHistorySerializer(self.history).data

    def _chem_event(self, data):
        chem = [e for e in (data.get("events") or []) if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1, "expected exactly one chemical event in public payload")
        return chem[0]

    def test_nop_technical_event_fields_stripped(self):
        """Worker-safety / agronomic-audit / self-graded keys must be absent from the event dict."""
        event = self._chem_event(self._anon_payload())
        leaked = NOP_TECHNICAL_EVENT_KEYS.intersection(event.keys())
        self.assertEqual(
            leaked,
            set(),
            f"NOP-technical / worker-safety / self-graded fields leaked to the consumer payload: "
            f"{sorted(leaked)}. These belong only on the certifier-facing NOP PDF.",
        )

    def test_worker_name_and_reg_values_not_in_blob(self):
        """Defense in depth: applicator PII + enforcement identifiers must not appear anywhere."""
        import json

        blob = json.dumps(self._anon_payload(), default=str)
        self.assertNotIn("CA QAL-4287", blob, "applicator certification leaked into public payload")
        self.assertNotIn("62719-621", blob, "EPA registration number leaked into public payload")
        self.assertNotIn("DPR-2026-001", blob, "CA DPR permit number leaked into public payload")

    # test_transparency_score_stripped_for_anonymous was deleted 2026-09-30 with the column.
    # `History.transparency_score` no longer exists as a field, so an assertNotIn against the
    # payload passes whatever the serializer does: it would stay green with the whole strip
    # removed. The guarantee now lives in history/tests/test_no_transparency_score_served.py,
    # which walks real serializer output and is verified against its own breaking edits.

    def test_worker_safety_keys_in_extra_data_are_stripped(self):
        """
        Regression for the nested-extra_data leak: REI/PHI/RUP/buffer_zone_meters are stripped
        at the top level of the event dict, but the standard V2 templates ALSO write REI/PHI
        into extra_data — and those keys were allow-listed, so the nested path leaked them to
        anonymous consumers. The sanitizer now subtracts the certifier-only set.
        """
        import json

        chem = ChemicalEvent.objects.filter(history=self.history).first()
        chem.extra_data = {
            "rei_hours": 4,
            "phi_days": 1,
            "restricted_use_pesticide": True,
            "buffer_zone_meters": 15,
            "volume_unit": "L",
            "organic_approved": "omri_listed",  # a benign key must still survive
        }
        chem.save(update_fields=["extra_data"])

        event = self._chem_event(self._anon_payload())
        nested = event.get("extra_data") or {}
        for leaked in ("rei_hours", "phi_days", "restricted_use_pesticide", "buffer_zone_meters", "volume_unit"):
            self.assertNotIn(
                leaked,
                nested,
                f"worker-safety/certifier key '{leaked}' leaked to consumers via event.extra_data",
            )
        blob = json.dumps(self._anon_payload(), default=str)
        self.assertNotIn('"rei_hours"', blob)
        self.assertNotIn('"buffer_zone_meters"', blob)

    def test_consumer_transparency_fields_survive(self):
        """The strip must not regress legitimate consumer content (what + third-party status + story)."""
        event = self._chem_event(self._anon_payload())
        self.assertEqual(event.get("commercial_name"), "Entrust SC")
        self.assertEqual(event.get("organic_approved"), "omri_listed")
        self.assertIn("input_status", event)


class PublicSerializerOperatorLeakageTests(TestCase):
    """The `operator` block (BasicUserSerializer) must never reach an anonymous
    consumer payload.

    Found live in production 2026-07-29: /public_history/ returned the grower's
    email, phone, is_superuser, user_type AND worksin_set — i.e. every other company
    and establishment that user runs. Scanning one product therefore disclosed the
    grower's contact details plus their unrelated farms. The owner previewing their
    own page still gets it; the consumer page never reads it.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="grower@operatorleak.test",
            password="x",
            first_name="Private",
            last_name="Grower",
        )
        self.user.phone = "+1-555-OPERATOR"
        self.user.save(update_fields=["phone"])

        self.company = Company.objects.create(name="Public Facing Farm")
        self.establishment = Establishment.objects.create(name="Shown Estate", company=self.company, state="CA")
        # A SECOND, unrelated operation the same grower runs — must not be disclosed
        # by scanning a product from the first one.
        self.other_company = Company.objects.create(name="Undisclosed Side Venture")
        self.other_establishment = Establishment.objects.create(
            name="Undisclosed Second Ranch", company=self.other_company, state="CA"
        )
        for company, establishment in (
            (self.company, self.establishment),
            (self.other_company, self.other_establishment),
        ):
            works_in = WorksIn.objects.create(user=self.user, company=company)
            works_in.establishments_in_charge.add(establishment)

        self.parcel = Parcel.objects.create(name="OP1", establishment=self.establishment, area=4.0)
        self.product = Product.objects.create(name="Hass Avocado")
        self.history = History.objects.create(
            name="Operator Leak Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _anon_payload(self):
        # No request context => _is_owner() is False => anonymous consumer view.
        return PublicHistorySerializer(self.history).data

    def test_operator_block_absent_for_anonymous(self):
        self.assertNotIn(
            "operator",
            self._anon_payload(),
            "operator (email/phone/user_type/other companies) leaked to the anonymous QR payload",
        )

    def test_operator_pii_and_other_operations_not_in_blob(self):
        import json

        blob = json.dumps(self._anon_payload(), default=str)
        for needle in [
            "grower@operatorleak.test",
            "+1-555-OPERATOR",
            "Undisclosed Side Venture",
            "Undisclosed Second Ranch",
        ]:
            self.assertNotIn(needle, blob, f"operator PII / cross-farm disclosure leaked: {needle}")

    def test_farm_identity_still_public(self):
        """Stripping operator must not hide the farm itself — that is legitimate transparency."""
        import json

        blob = json.dumps(self._anon_payload(), default=str)
        self.assertIn("Shown Estate", blob)

    def test_operator_still_present_for_authenticated_owner(self):
        """The producer dashboard (ProfileProduction) renders operator.full_name /
        operator.email off this exact endpoint, so the gate must be ANONYMOUS-ONLY.
        A future 'simplification' that drops the field unconditionally would blank
        the Operator card in the farmer's own dashboard — this test catches that."""
        from rest_framework.test import APIClient

        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)
        resp = client.get(f"/api/histories/{self.history.public_id}/public_history/")
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        operator = resp.json().get("operator")
        self.assertIsNotNone(operator, "owner (producer dashboard) lost its operator block")
        self.assertEqual(operator.get("email"), "grower@operatorleak.test")


class PublicSerializerDriftWarningLeakageTests(TestCase):
    """Regression: the OSP drift finding must never reach the anonymous consumer payload.

    `drift_warning` is stamped on ChemicalEvent/SoilManagementEvent by
    certifications.services.drift_detector when a logged input is not on the farm's active
    Organic System Plan. It carries a free-text nonconformance narrative, the internal
    `osp_id`/`osp_version`, a 7 CFR citation, and `resolved_via: "unresolved"` — internal
    audit data about the farmer's own paperwork, self-incriminating by nature.

    Found on the live anonymous payload of a published production 2026-07-31:
        "Soil amendment 'Aged horse manure (uncomposted, local stable)' not in active OSP
         approved inputs"  /  cfr_reference: "7 CFR 205.400(f)(2)"

    Two reasons this needs its own test rather than relying on the generic key strip:
      1. `to_representation` pops TOP-LEVEL keys and keys inside `extra_data` only — it does
         NOT descend into nested objects, so nothing inside `drift_warning` was ever filtered.
      2. `_build_drift_warning` can attach `ca_dpr_permit_status.permit_number` (a CA DPR
         restricted-materials permit). That path is dormant today because
         CA_RESTRICTED_KEYWORDS is empty, but it would have gone straight to consumers.

    The producer sees drift findings via DriftFindingsBanner on ProfileProduction — the
    correct audience for a compliance finding.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="drift@test.com", password="x")
        self.company = Company.objects.create(name="Drift Farm")
        self.establishment = Establishment.objects.create(name="D1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="DP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="Drift Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        self.chemical_drift = {
            "osp_id": 27,
            "osp_version": 1,
            "reason": "National List substance not in active OSP approved inputs",
            "input_label": "Avenger AG (d-limonene 70%)",
            "cfr_reference": "7 CFR 205.400(f)(2)",
            "resolved_via": "national_list",
            "ca_dpr_permit_status": {"status": "required", "permit_number": "DPR-2026-0099"},
        }
        self.soil_drift = {
            "osp_id": 27,
            "osp_version": 1,
            "reason": "Soil amendment 'Aged horse manure (uncomposted, local stable)' "
            "not in active OSP approved inputs",
            "input_label": "Aged horse manure (uncomposted, local stable)",
            "cfr_reference": "7 CFR 205.400(f)(2)",
            "resolved_via": "unresolved",
        }
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.HERBICIDE,
            commercial_name="Avenger AG",
            drift_warning=self.chemical_drift,
            date=timezone.now(),
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type=SoilManagementEvent.ORGANIC_MATTER,
            drift_warning=self.soil_drift,
            date=timezone.now(),
        )

    def _public_events(self):
        return PublicHistorySerializer(self.history).data.get("events") or []

    def test_drift_warning_key_absent_from_every_event(self):
        offenders = [e.get("type") for e in self._public_events() if "drift_warning" in e]
        self.assertEqual(
            offenders,
            [],
            f"drift_warning (an internal OSP nonconformance finding) leaked on: {offenders}",
        )

    def test_nonconformance_narrative_not_in_payload(self):
        """Defense in depth: the reason text must not appear anywhere in the blob."""
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("not in active OSP approved inputs", blob)
        self.assertNotIn("205.400(f)(2)", blob)
        self.assertNotIn("unresolved", blob)

    def test_nested_dpr_permit_number_not_in_payload(self):
        """The nested CA DPR permit number must not ride along inside drift_warning.

        to_representation never descends into nested objects, so this could only ever be
        prevented by not serializing drift_warning at all.
        """
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("DPR-2026-0099", blob, "CA DPR permit number leaked via drift_warning")

    def test_legitimate_event_fields_survive(self):
        """Sanity: dropping drift_warning must not remove the practice record itself."""
        chem = [e for e in self._public_events() if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1)
        self.assertEqual(chem[0].get("commercial_name"), "Avenger AG")


class PublicSerializerWorkerNameAndLabBlobTests(TestCase):
    """Regression (2026-07-31 consumer editorial review): two leaks that the existing
    key-based guards could not catch because nobody had named the fields.

    1. ``cleaned_by`` — free text for "person who performed or verified the cleaning",
       holding real worker names. It rendered on the live consumer card as
       "Cleaned By: Miguel Ramirez (Farm Manager)", one tap from collapsed. The codebase
       already masks ``performed_by`` to initials (``_public_performer``) and strips
       ``applicator_name`` outright, so this was an inconsistency, not a policy.

    2. ``test_results`` — the raw soil-lab JSONField, dumped whole. Its sibling
       ``water_test_results`` is deliberately withheld AND regression-tested
       (test_water_quality.py), and ``lab_name`` is excluded from
       ``ALLOWED_EXTRA_DATA_KEYS`` — yet the same information rode through this blob.
       An unfiltered JSON blob on a public endpoint is the same structural mistake as the
       old extra_data deny-list.

    ``cleaning_protocol_reference`` (an internal SOP id) and ``sanitizer_nop_reference``
    (a raw CFR citation) are covered here too — operator vocabulary, not consumer facts.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="worker@test.com", password="x")
        self.company = Company.objects.create(name="Worker Farm")
        self.establishment = Establishment.objects.create(name="W1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="WP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Hass Avocado")
        self.history = History.objects.create(
            name="Worker Name Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            equipment_operation_type="CL",
            cleaning_method="Pressure wash + manual scrub",
            cleaning_materials_used="Water, BioSafe SaniDate",
            cleaned_by="Miguel Ramirez (Farm Manager)",
            cleaning_protocol_reference="SOP-CLEAN-001 (NOP 205.272 Compliance)",
            sanitizer_nop_reference="§ 205.605(b) - Sodium hypochlorite",
            date=timezone.now(),
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type=SoilManagementEvent.SOIL_TEST,
            test_results={
                "lab_name": "A&L Western Laboratories",
                "report_date": "2026-07-18",
                "analyst": "J. Whitfield",
                "nitrogen": 45,
                "potassium": 210,
                "cec": 14.2,
                "zinc_ppm": 1.8,
            },
            date=timezone.now(),
        )

    def _events(self):
        return PublicHistorySerializer(self.history).data.get("events") or []

    def test_worker_name_and_operator_reference_keys_absent(self):
        banned = {"cleaned_by", "cleaning_protocol_reference", "sanitizer_nop_reference"}
        leaked = {k for e in self._events() for k in e.keys() if k in banned}
        self.assertEqual(leaked, set(), f"operator-only keys leaked to consumers: {sorted(leaked)}")

    def test_worker_name_value_not_anywhere_in_payload(self):
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn(
            "Miguel Ramirez",
            blob,
            "a worker's name reached the public product page — performed_by is masked and "
            "applicator_name is stripped for exactly this reason",
        )
        self.assertNotIn("SOP-CLEAN-001", blob)
        self.assertNotIn("205.605(b)", blob)

    def test_raw_test_results_blob_absent(self):
        leaked = [e.get("type") for e in self._events() if "test_results" in e]
        self.assertEqual(leaked, [], "the raw soil-lab JSONField leaked to consumers")

    def test_lab_analyst_and_numeric_panel_not_in_payload(self):
        """Only the curated §E-2 facts survive; the panel and the analyst do not.

        🔴 FLAKY-TEST FIX 2026-08-15. This used to substring-search the whole serialized blob
        for "cec" and failed at random: a public_id UUID of
        `39552156-585f-4755-a5a6-d3cec7c7e239` contains "cec", so the assertion fired on an
        identifier rather than on leaked lab data. The pre-existing `.replace("recent", "")`
        was the same collision being patched one word at a time.

        A three-letter token cannot be searched across a document containing UUIDs, hashes and
        filenames. Assert against the EVENT FIELDS instead — which is also the real claim:
        the numeric soil panel must not appear as data, whatever any identifier happens to
        spell.
        """
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("J. Whitfield", blob, "lab analyst name leaked")

        panel_keys = {"cec", "cec_meq_100g", "test_results", "lab_analyst", "analyst"}
        # The VALUES this fixture puts in the panel. Asserting on the readings rather than on
        # the token "cec" — a three-letter substring collides with UUIDs (that is the bug this
        # test had) and with ordinary prose a grower might write, e.g. a worker named Cecilia.
        panel_values = {"14.2", "45", "210", "1.8"}
        for event in self._events():
            with self.subTest(event=event.get("type")):
                leaked = panel_keys & set(event.keys())
                self.assertEqual(leaked, set(), f"numeric soil panel leaked to consumers: {leaked}")
                # Values too: a panel smuggled into a free-text field is the same leak. Only
                # free text is searched — a numeric reading has no business inside prose, while
                # legitimate numeric FIELDS (area, yield) obviously carry numbers.
                for key in ("description", "observation"):
                    text = event.get(key)
                    if isinstance(text, str):
                        for reading in panel_values:
                            self.assertNotIn(
                                reading,
                                text,
                                f"soil panel reading {reading} surfaced inside `{key}`",
                            )

    def test_curated_lab_facts_still_survive(self):
        """§E-2: an independent lab IS third-party evidence — keep the facts."""
        soil = [e for e in self._events() if e.get("type") == "soil_management"]
        self.assertEqual(len(soil), 1)
        self.assertEqual(soil[0].get("lab_name"), "A&L Western Laboratories")
        self.assertEqual(soil[0].get("lab_report_date"), "2026-07-18")

    def test_the_whole_cleanout_event_is_withheld_from_shoppers(self):
        """SUPERSEDED 2026-08-21. This test used to assert the opposite, and was right to.

        Written 2026-07-31, when the policy was "mask the worker name, keep the cleaning
        evidence" — the fix for `cleaned_by` rendering a real name on the consumer card. A
        later decision went further: `claim_authority._CONSUMER_WITHHELD_PRODUCTION_SUBTYPES`
        withholds the entire `EM` subtype from consumer surfaces because a cleanout/purge
        narrative "reveals split-operation handling out of context" — a shopper reading
        "pressure-washed the line before the organic run" infers the farm also runs
        conventional product, which § 205.272 requires the operation to MANAGE, not to
        justify on a QR page.

        The stricter rule supersedes the looser one, so this now pins the current behaviour.
        The evidence itself is not lost — it is on the producer's own timeline
        (`OwnerSeesWithheldSubtypesTests` in test_consumer_production_subtypes) and in the
        certifier packet, which builds from AuditExportService and never applies this filter.
        Those are the two audiences § 205.272 is written for.
        """
        # The production block sets "type" to the SUBTYPE code (here "EM"); event_type is
        # the numeric family (1 = production).
        prod = [e for e in self._events() if e.get("event_type") == 1]
        self.assertEqual(prod, [], "an equipment cleanout reached the anonymous QR payload")

    def test_the_cleaning_evidence_still_reaches_the_operator(self):
        """The other half: withholding it from shoppers must not delete it.

        A farmer who logs an equipment cleaning has to be able to see it — this was broken
        until 2026-08-21, when the consumer filter was found running against the owner's own
        timeline too.
        """
        from django.test import RequestFactory

        from users.models import User as UserModel

        owner = UserModel.objects.create_user(email="cleanowner@test.com", password="x")
        owner.companies.add(self.company)
        request = RequestFactory().get("/x/")
        request.user = owner

        events = PublicHistorySerializer(self.history, context={"request": request}).data.get("events") or []
        prod = [e for e in events if e.get("event_type") == 1]
        self.assertEqual(len(prod), 1, "the producer lost their own equipment-cleaning record")
        self.assertEqual(prod[0].get("cleaning_method"), "Pressure wash + manual scrub")
        self.assertEqual(prod[0].get("cleaning_materials_used"), "Water, BioSafe SaniDate")


class PublicSerializerForcePublicViewTests(TestCase):
    """The consumer product page must render identically for the owner and for a shopper.

    `to_representation` strips certifier-only event fields only `if not self._is_owner(obj)`.
    That exemption is right for the producer DASHBOARD (which uses the same serializer and
    needs the full record), but the transparency endpoint IS the consumer page — so a
    logged-in grower scanning their own QR link saw REI, PHI, applicator name and EPA
    registration number rendered on their own product page, with no way to tell that the
    public version differs.

    That is the backend half of the same defect as EventPreviewModal: both surfaces showed
    the farmer a version of their product page that no shopper ever receives. A grower makes
    decisions about what is safe to record based on those screens.

    `force_public_view` in the serializer context disables the exemption.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="owner@forcepublic.test", password="x")
        self.company = Company.objects.create(name="ForcePublic Farm")
        self.user.companies.add(self.company)
        self.establishment = Establishment.objects.create(name="FP1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="FPP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="ForcePublic Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            applicator_name="Ana Torres",
            applicator_certification="CA QAL-4287",
            epa_registration_number="62719-621",
            rei_hours=Decimal("48.0"),
            phi_days=Decimal("14.0"),
            buffer_zone_meters=Decimal("30.0"),
            date=timezone.now(),
        )

    def _request(self, user):
        """A real request — the serializer calls request.build_absolute_uri for the QR image."""
        from django.test import RequestFactory

        req = RequestFactory().get(f"/api/transparency/{self.history.public_id}/")
        req.user = user
        return req

    def _anonymous_request(self):
        from django.contrib.auth.models import AnonymousUser

        return self._request(AnonymousUser())

    def _events(self, **context):
        data = PublicHistorySerializer(self.history, context=context).data
        return data.get("events") or []

    def test_owner_without_force_public_view_keeps_full_record(self):
        """The producer dashboard path is unchanged — it still needs the whole record."""
        events = self._events(request=self._request(self.user))
        chem = [e for e in events if e.get("type") == "chemical"][0]
        self.assertIn("rei_hours", chem, "the dashboard path must keep certifier fields")

    def test_force_public_view_strips_certifier_fields_for_the_owner(self):
        events = self._events(request=self._request(self.user), force_public_view=True)
        chem = [e for e in events if e.get("type") == "chemical"][0]
        leaked = NOP_TECHNICAL_EVENT_KEYS.intersection(chem.keys())
        self.assertEqual(
            leaked,
            set(),
            f"owner saw certifier-only fields on the CONSUMER page: {sorted(leaked)}",
        )

    # test_force_public_view_strips_the_self_graded_score_for_the_owner was deleted 2026-09-30
    # with the column, for the same reason as above. force_public_view itself is still
    # covered, and covered better, by test_owner_and_anonymous_consumer_views_are_identical
    # below: that one compares the two payloads byte for byte instead of naming one key.

    def test_owner_and_anonymous_consumer_views_are_identical(self):
        """The strongest form of the guarantee: same page, byte for byte, for both."""
        import json

        owner_view = PublicHistorySerializer(
            self.history, context={"request": self._request(self.user), "force_public_view": True}
        ).data
        anon_view = PublicHistorySerializer(self.history, context={"request": self._anonymous_request()}).data
        self.assertEqual(
            json.dumps(owner_view.get("events"), sort_keys=True, default=str),
            json.dumps(anon_view.get("events"), sort_keys=True, default=str),
            "the owner's view of their own product page differs from what shoppers receive",
        )


class OwnerRetainsOperatorDataTests(TestCase):
    """The owner-gate must keep the PRODUCER whole while keeping consumers clean.

    PublicHistorySerializer does not only serve the consumer QR page — it also feeds the
    producer's ProfileProduction timeline (carbon `complete_summary` builds it with
    `context={"request": request}`). An earlier version of the 2026-07-31 fix DELETED
    `drift_warning` / `cleaned_by` / `test_results` / the operator references from
    `get_events()` outright, which silently broke `DriftFindingsBanner` on the producer
    dashboard — the very surface whose existence justifies withholding drift findings from
    shoppers.

    The correct mechanism is `_CERTIFIER_ONLY_EVENT_FIELDS` (owner-gated in
    `to_representation`), not deletion. These tests pin both halves so the two audiences
    cannot drift apart again.
    """

    OPERATOR_ONLY = (
        "drift_warning",
        "cleaned_by",
        "cleaning_protocol_reference",
        "sanitizer_nop_reference",
        "test_results",
    )

    def setUp(self):
        self.user = User.objects.create_user(email="ownerdata@test.com", password="x")
        self.company = Company.objects.create(name="OwnerData Farm")
        self.user.companies.add(self.company)
        self.establishment = Establishment.objects.create(name="OD1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="ODP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Hass Avocado")
        self.history = History.objects.create(
            name="OwnerData Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.HERBICIDE,
            commercial_name="Avenger AG",
            drift_warning={
                "osp_id": 27,
                "reason": "not in active OSP approved inputs",
                "cfr_reference": "7 CFR 205.400(f)(2)",
            },
            date=timezone.now(),
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            equipment_operation_type="CL",
            cleaned_by="Miguel Ramirez (Farm Manager)",
            cleaning_protocol_reference="SOP-CLEAN-001",
            sanitizer_nop_reference="\u00a7 205.605(b)",
            date=timezone.now(),
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type=SoilManagementEvent.SOIL_TEST,
            test_results={"lab_name": "A&L Western Laboratories", "nitrogen": 45},
            date=timezone.now(),
        )

    def _request(self, user):
        from django.test import RequestFactory

        req = RequestFactory().get("/x/")
        req.user = user
        return req

    def _keys(self, **context):
        data = PublicHistorySerializer(self.history, context=context).data
        return {k for e in (data.get("events") or []) if isinstance(e, dict) for k in e}

    def test_owner_keeps_drift_warning_for_the_dashboard_banner(self):
        """DriftFindingsBanner (ProfileProduction) reads this — deleting it broke the banner."""
        self.assertIn("drift_warning", self._keys(request=self._request(self.user)))

    def test_owner_keeps_every_operator_only_field(self):
        keys = self._keys(request=self._request(self.user))
        missing = [f for f in self.OPERATOR_ONLY if f not in keys]
        self.assertEqual(missing, [], f"producer lost operator data from their own timeline: {missing}")

    def test_anonymous_consumer_gets_none_of_them(self):
        keys = self._keys()
        leaked = [f for f in self.OPERATOR_ONLY if f in keys]
        self.assertEqual(leaked, [], f"operator-only fields leaked to an anonymous consumer: {leaked}")

    def test_owner_on_the_consumer_page_gets_none_of_them(self):
        """force_public_view: the grower previewing their own QR link sees the shopper view."""
        keys = self._keys(request=self._request(self.user), force_public_view=True)
        leaked = [f for f in self.OPERATOR_ONLY if f in keys]
        self.assertEqual(leaked, [], f"owner saw operator-only fields on the CONSUMER page: {leaked}")


class PublicSerializerSelfAttestedVerificationTests(TestCase):
    """
    2026-08-01 (consumer editorial review, round 2).

    A business/certification event carries a FARMER-ENTERED ``verification_status``. On the
    live avocado page it rendered as a public Key Detail reading "Verification Status:
    Verified" — sitting directly above the same card's "Self Reported" chip. A self-attested
    "Verified" on a consumer surface is exactly the self-created-label class the EU ECGT
    2024/825 bans (live 2026-09-27) and an FTC 16 CFR 260.4 general-benefit risk.

    What must survive: the certificate NUMBER and the CERTIFIER NAME. Those are checkable by
    a buyer against the issuing body, which is the whole point of publishing them.

    NOT the same field as ``Certification.verification_status`` on the FARM, which backs the
    "Verified via USDA Organic Integrity Database" badge — that one is a database
    cross-reference Trazo performs, not a claim the farmer types.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="selfattest@test.com", password="x")
        self.company = Company.objects.create(name="SelfAttest Farm")
        self.establishment = Establishment.objects.create(name="SA1", company=self.company, state="CA")
        works_in = WorksIn.objects.create(user=self.user, company=self.company)
        works_in.establishments_in_charge.add(self.establishment)
        self.parcel = Parcel.objects.create(name="SAP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Hass Avocado")
        self.history = History.objects.create(
            name="SelfAttest Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        BusinessEvent.objects.create(
            history=self.history,
            type=BusinessEvent.CERTIFICATION,
            certification_type="global_gap",
            certificate_number="DEMO-GGP-0002",
            verified_certifier_name="Coast Range Assurance Services",
            verification_status="verified",
            date=timezone.now(),
        )

    def _business_event(self):
        data = PublicHistorySerializer(self.history).data
        events = [e for e in (data.get("events") or []) if e.get("type") == "business"]
        self.assertEqual(len(events), 1, "expected exactly one business event in public payload")
        return events[0]

    def test_farmer_entered_verification_status_is_stripped(self):
        event = self._business_event()
        self.assertNotIn(
            "verification_status",
            event,
            'self-attested "Verified" must not ship on the anonymous consumer payload (ECGT/FTC)',
        )

    def test_the_word_verified_does_not_reach_the_consumer_blob(self):
        """Defense in depth — the value, not just the key."""
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn(
            '"verified"',
            blob,
            'a self-attested "verified" value leaked somewhere in the consumer payload',
        )

    def test_checkable_certificate_facts_still_public(self):
        """Guards against over-stripping: a buyer must still be able to verify the claim.

        2026-08-09 policy reconciliation: this test originally required the farmer-typed
        certifier NAME to ship too. The claim authority (2026-08-03, written after this
        test) is stricter — `public_certifier_name` withholds the name unless a USDA-OID
        database-verified certification backs it, because a typed name beside a
        certificate number reads as third-party attestation (ECGT 2024/825; FTC 16 CFR
        260.6). Strict wins for launch. The certificate NUMBER alone remains the
        buyer-checkable fact; the name unlocks on a database-verified match (case below).
        """
        event = self._business_event()
        self.assertEqual(event.get("certificate_number"), "DEMO-GGP-0002")
        self.assertIsNone(
            event.get("verified_certifier_name"),
            "farmer-typed certifier name must be withheld without a database-verified certification",
        )

    def test_certifier_name_ships_when_database_verified(self):
        """The strict gate opens on real evidence: a USDA-OID-verified certification."""
        from certifications.models import Certification
        from history.services.claim_authority import DATABASE_VERIFICATION_SOURCE

        Certification.objects.create(
            establishment=self.establishment,
            certification_type="global_gap",
            verification_status="verified",
            verification_source=DATABASE_VERIFICATION_SOURCE,
        )
        event = self._business_event()
        self.assertEqual(event.get("verified_certifier_name"), "Coast Range Assurance Services")

    def test_owner_still_sees_their_own_verification_status(self):
        """The producer's dashboard reads the same serializer; owner-gating must keep it whole."""
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        data = PublicHistorySerializer(self.history, context={"request": request}).data
        events = [e for e in (data.get("events") or []) if e.get("type") == "business"]
        self.assertEqual(events[0].get("verification_status"), "verified")


class PublicPayloadFinalAuditTests(TestCase):
    """
    The four P0s an independent audit found on 2026-08-02, each verified live on the wire
    before being fixed. All four share one shape: a field that IS stripped, reaching the
    consumer anyway through a second path nobody had audited.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="finalaudit@test.com", password="x")
        self.company = Company.objects.create(name="Final Audit Farm")
        self.establishment = Establishment.objects.create(
            name="FA1",
            company=self.company,
            state="CA",
            description=(
                "A 950-acre premium citrus operation generating $18.2M annually with 45% "
                "premium pricing through verified carbon-negative practices."
            ),
        )
        works_in = WorksIn.objects.create(user=self.user, company=self.company)
        works_in.establishments_in_charge.add(self.establishment)
        self.parcel = Parcel.objects.create(
            name="FAP1",
            establishment=self.establishment,
            area=5.0,
            map_metadata={
                "center": {"lat": 36.1, "lng": -119.2},
                "zoom": 15,
                "soil_health_score": 92,
                "biodiversity_score": 92,
                "water_efficiency_rating": "A+",
                "yield_vs_conventional": "+85%",
                "carbon_credits_eligible": True,
            },
        )
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Final Audit Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        GeneralEvent.objects.create(
            history=self.history,
            activity_type="other",
            is_contamination_incident=True,
            contamination_source="spray_drift",
            contamination_affected_area=3.5,
            corrective_action_taken=("Notified CCOF inspector within 24 hours. Neighbour Johnson Citrus advised."),
            certifier_notified=True,
            date=timezone.now(),
        )

    def _anon(self):
        return PublicHistorySerializer(self.history).data

    # --- P0: farm financials + FTC copy in free-text establishment fields -------------------
    def test_farm_financials_are_redacted_from_the_public_description(self):
        import json

        blob = json.dumps(self._anon(), default=str)
        for forbidden in ("$18.2M", "45% premium pricing", "premium pricing", "carbon-negative"):
            self.assertNotIn(
                forbidden,
                blob,
                f"{forbidden!r} reached the anonymous payload — farm P&L and unsupportable "
                "market claims (FTC 16 CFR 260.6) must be redacted by "
                "history.services.privacy.public_free_text.",
            )

    def test_redaction_covers_the_company_bio_and_practice_list_too(self):
        """
        The first pass covered the five establishment prose fields and missed two more that
        carry the same free text: `company.description` and the `sustainability_practices`
        LIST ("Carbon-negative certified"). Found by re-scanning the wire after the fix, which
        is the only reason it was caught.
        """
        from history.services.privacy import public_free_text, public_free_text_list

        self.assertNotIn(
            "carbon-negative",
            (public_free_text("Pioneering carbon-negative farming across California.") or "").lower(),
        )
        cleaned = public_free_text_list(["Carbon-negative certified", "Cover cropping"])
        self.assertEqual(cleaned, ["Cover cropping"])

    def test_redaction_covers_noun_shaped_certification_labels(self):
        """
        The verb-keyed rules ("verified", "certified by", "USDA certified") missed the shape
        farmers actually write: a noun phrase where the certifying verb trails, or where a
        word intervenes between USDA and "Certified". Every string below shipped in a demo
        seeder and reached shoppers intact until 2026-08-07.

        `sustainability_practices` no longer reaches any public payload at all, but the same
        helper still guards `about`, `main_activities`, `location_highlights`,
        `custom_message` and `company.description`, where the claim can be typed as prose.
        """
        from history.services.privacy import public_free_text, public_free_text_list

        for claim in (
            "USDA Organic Certified",
            "Certified Organic",
            "Real Organic Project Certified",
        ):
            self.assertIsNone(public_free_text(claim), f"{claim!r} survived redaction")

        # The bracketed certifier goes with the claim — redacting to a bare "(CCOF)" still
        # puts an accrediting body's name in front of a shopper.
        self.assertIsNone(public_free_text("USDA Organic Certified (CCOF)"))

        # Entries losing anything to redaction are dropped whole; honest practices survive.
        self.assertEqual(
            public_free_text_list(["USDA Organic Certified", "Cover Cropping", "Drip Irrigation"]),
            ["Cover Cropping", "Drip Irrigation"],
        )

    def test_redaction_keeps_the_rest_of_the_growers_own_words(self):
        """Guards against over-redaction: only the money and the claims come out."""
        import json

        blob = json.dumps(self._anon(), default=str)
        self.assertIn("citrus operation", blob)

    # --- P0: self-assigned sustainability grades in parcel.map_metadata ---------------------
    def test_map_metadata_publishes_only_map_keys(self):
        import json

        blob = json.dumps(self._anon(), default=str)
        for grade in (
            "soil_health_score",
            "biodiversity_score",
            "water_efficiency_rating",
            "yield_vs_conventional",
            "carbon_credits_eligible",
        ):
            self.assertNotIn(
                grade,
                blob,
                f"{grade} is a self-assigned grade; map_metadata must be allow-listed to "
                "map-rendering keys (Trazo Test #5 / ECGT 2024/825).",
            )

    def test_map_metadata_still_carries_what_a_map_needs(self):
        data = self._anon()
        meta = (data.get("parcel") or {}).get("map_metadata") or {}
        self.assertIn("center", meta, "the allow-list must not break the map itself")
        self.assertIn("zoom", meta)

    # --- P0: NOP contamination filing ------------------------------------------------------
    def test_contamination_filing_narrative_is_owner_only(self):
        event = [e for e in (self._anon().get("events") or []) if e.get("is_contamination_incident")][0]
        self.assertIsNone(
            event.get("corrective_action_taken"),
            "the corrective-action narrative names the certifier and the neighbouring farm",
        )
        self.assertIsNone(event.get("certifier_notified"))

    def test_the_incident_itself_is_still_disclosed(self):
        """Transparency, not concealment: the shopper still learns an incident was recorded."""
        event = [e for e in (self._anon().get("events") or []) if e.get("is_contamination_incident")][0]
        self.assertTrue(event["is_contamination_incident"])
        self.assertEqual(event.get("contamination_source"), "spray_drift")

    def test_owner_keeps_the_whole_filing(self):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        data = PublicHistorySerializer(self.history, context={"request": request}).data
        event = [e for e in (data.get("events") or []) if e.get("is_contamination_incident")][0]
        self.assertIn("CCOF", event["corrective_action_taken"])
        self.assertTrue(event["certifier_notified"])


class RecordIdIsOwnerOnlyTests(TestCase):
    """The real event pk reaches the producer and never a shopper.

    Added 2026-08-21. Every event on this payload is keyed `chemical_0` / `production_3` —
    synthetic and POSITIONAL. That is correct for a public endpoint (primary keys are
    enumerable) and it left the producer's own Production Profile unable to address the very
    records it renders: there was no id to open a correction against, so the only per-event
    affordance in the product sat on season-plan rows, and an input logged outside the plan —
    a bloom fungicide, say — had none at all.

    `record_id` is therefore owner-only, on the same list and the same mechanism as
    `drift_warning`: popped for every non-owner, and popped for the owner previewing the
    consumer view through `force_public_view`.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from company.models import Company, Establishment
        from history.models import ChemicalEvent, History
        from product.models import Parcel, Product

        User = get_user_model()
        self.user = User.objects.create_user(email="recordid@test.com", password="x")
        self.company = Company.objects.create(name="RecordId Farm")
        self.user.companies.add(self.company)
        est = Establishment.objects.create(name="RI1", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="RIP1", establishment=est, area=5.0)
        self.history = History.objects.create(
            name="RecordId Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apple"),
            parcel=parcel,
            published=True,
        )
        self.event = ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            commercial_name="Rex Lime Sulfur",
            date=timezone.now(),
        )

    def _events(self, **context):
        from history.serializers import PublicHistorySerializer

        return PublicHistorySerializer(self.history, context=context).data.get("events") or []

    def _owner_request(self):
        from django.test import RequestFactory

        req = RequestFactory().get("/x/")
        req.user = self.user
        return req

    def test_the_owner_can_address_the_record(self):
        events = self._events(request=self._owner_request())
        self.assertTrue(events)
        self.assertEqual(events[0].get("record_id"), self.event.id)

    def test_a_chemical_event_names_its_family_like_every_other_one(self):
        """The correction endpoint takes this as `?event_type=`; chemical alone omitted it."""
        events = self._events(request=self._owner_request())
        self.assertEqual(events[0].get("event_type"), 2)

    def test_an_anonymous_shopper_gets_no_database_ids(self):
        for event in self._events():
            self.assertIsNone(event.get("record_id"))
            # The synthetic, positional key stays — that is what the consumer page keys on.
            self.assertTrue(str(event.get("id", "")).startswith("chemical_"))

    def test_the_owner_previewing_the_consumer_view_gets_none_either(self):
        events = self._events(request=self._owner_request(), force_public_view=True)
        for event in events:
            self.assertIsNone(event.get("record_id"))


class TillageWireTests(TestCase):
    """The four tillage facts, split between the buyer page and the certifier packet.

    🔴 2026-09-06. `tillage_type`, `tillage_intensity`, `tillage_direction` and
    `residue_management` are collected by SoilManagementTab and persisted in `extra_data`
    (SoilManagementEvent has no columns for them). All four were allow-listed onto the
    anonymous payload, and the frontend display registry declared NONE of them -- so every
    one was scrapable JSON with no component drawing it, and the producer's own detail modal
    showed a tillage pass as a date, a label and an acreage.

    That is the exact finding this file already records twice: `storage_location` /
    `storage_temperature_f` (2026-08-09) and the five operator keys in
    test_operator_only_keys_are_off_the_public_wire (2026-08-15). Neither sweep reached soil,
    because both were written against a PLANTING event.

    The split now shipped:

      PUBLIC   tillage_type        a named practice class ("No-till", "Minimum till") a buyer
                                   can check against the rest of the season's records
               residue_management  what happened to last crop's plant material -- physical,
                                   plain, and the fact the grower's own notes lead with

      WITHHELD tillage_intensity   high/medium/low/CONSERVATION is a grower-assigned rating of
                                   their own soil disturbance against no published criteria:
                                   the production_efficiency shape, and "Conservation" as a
                                   self-awarded grade is the EU ECGT 2024/825 self-created
                                   label class
               tillage_direction   "across_slope" is unreadable without the block's slope,
                                   which the buyer page does not publish, and the form sells
                                   it as "Erosion control"

    Both withheld fields still reach the producer modal and the certifier packet
    (audit_export_service.TILLAGE_PRACTICE_LABELS). This asserts they stop at the wire.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="tillage@test.com", password="x")
        self.company = Company.objects.create(name="Tillage Farm")
        self.establishment = Establishment.objects.create(name="T1", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="TP1", establishment=self.establishment, area=7.5)
        self.product = Product.objects.create(name="Spinach")
        self.history = History.objects.create(
            name="Tillage Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type=SoilManagementEvent.TILLAGE,
            date=timezone.now(),
            extra_data={
                "tillage_type": "minimum_till",
                "tillage_intensity": "medium",
                "tillage_direction": "across_slope",
                "residue_management": "incorporated",
            },
        )

    def _tillage_event(self):
        events = PublicHistorySerializer(self.history).data.get("events") or []
        soil = [e for e in events if e.get("type") == "soil_management"]
        self.assertEqual(len(soil), 1, f"expected one soil event on the public payload, got {len(soil)}")
        return soil[0]

    def _extra(self):
        return self._tillage_event().get("extra_data") or {}

    def test_practice_facts_reach_the_buyer_page(self):
        """Anti-vacuity: if these stop shipping, the withholding assertions below prove nothing."""
        extra = self._extra()
        self.assertEqual(extra.get("tillage_type"), "minimum_till")
        self.assertEqual(extra.get("residue_management"), "incorporated")

    def test_self_assigned_intensity_is_off_the_wire(self):
        self.assertNotIn(
            "tillage_intensity",
            self._extra(),
            "tillage_intensity is a grower-assigned rating of their own soil disturbance; "
            "it has no consumer renderer and must not ride the anonymous payload",
        )

    def test_direction_is_off_the_wire(self):
        self.assertNotIn(
            "tillage_direction",
            self._extra(),
            "tillage_direction has no consumer renderer and is unreadable without slope data "
            "the buyer page does not publish",
        )

    def test_withheld_values_absent_from_the_whole_blob(self):
        """Defense in depth: not just the key -- the value must not surface under another name."""
        import json

        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("across_slope", blob, "tillage_direction value leaked into the public blob")
        self.assertNotIn("tillage_intensity", blob, "tillage_intensity key leaked into the public blob")


class PublicFreeTextCommercialReferenceTests(TestCase):
    """Run 8 (R8-18): the buyer page printed "invoice CI-26-04471" from a spray note while the
    structured `purchase_invoice` beside it was withheld. Invoice, order, receipt and account
    numbers leave public free text; lot numbers, the traceability a buyer reads for, stay;
    the record itself and the certifier's copy keep everything."""

    NOTE = (
        "Spring N: Feather Meal 12-0-0, Lot DTE-FM-2512-880, invoice CI-26-04471, PO #7781, "
        "receipt: R-2245; paid against CI-26-04471. Applied in order to feed the bloom."
    )

    def setUp(self):
        self.user = User.objects.create_user(email="r8ref@test.com", password="x")
        company = Company.objects.create(name="Ref Farm")
        est = Establishment.objects.create(name="R1", company=company, state="OR")
        parcel = Parcel.objects.create(name="RP1", establishment=est, area=5.0)
        self.history = History.objects.create(
            name="Ref Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Blueberries"),
            parcel=parcel,
            operator=self.user,
            published=True,
        )
        self.event = ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Feather Meal",
            purchase_invoice="CI-26-04471",
            observation=self.NOTE,
            date=timezone.now(),
        )

    def _public_note(self):
        events = PublicHistorySerializer(self.history).data.get("events") or []
        chem = [e for e in events if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1)
        return chem[0]["observation"]

    def test_invoice_order_and_receipt_numbers_are_withheld(self):
        note = self._public_note()
        for ref in ("CI-26-04471", "7781", "R-2245"):
            self.assertNotIn(ref, note)
        self.assertIn("[reference withheld]", note)

    def test_lot_numbers_and_ordinary_words_are_kept(self):
        note = self._public_note()
        self.assertIn("Lot DTE-FM-2512-880", note)
        self.assertIn("in order to feed the bloom", note)

    def test_the_record_keeps_every_reference(self):
        self._public_note()
        self.event.refresh_from_db()
        self.assertEqual(self.event.observation, self.NOTE)
        self.assertEqual(self.event.purchase_invoice, "CI-26-04471")
