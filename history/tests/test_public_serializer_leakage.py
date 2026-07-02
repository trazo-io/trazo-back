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

from company.models import Company, Establishment
from history.models import BusinessEvent, ChemicalEvent, History, ProductionEvent
from history.serializers import PublicHistorySerializer
from product.models import Parcel, Product
from users.models import User

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
# to the photo-evidence display; only the numeric self-graded transparency_score is stripped.)
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
        self.establishment = Establishment.objects.create(name="L1", company=self.company)
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
            transparency_score=0.0,
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
    """Regression: carbon_credits_unit must NOT surface when carbon_credits_earned is null/zero.

    A row with business_type='certification' (or any non-carbon-credits activity) but a
    legacy carbon_credits_unit='tCO2e' default (the BusinessEvent model field default)
    would otherwise render an orphan "Carbon Credits Unit: tCO2e" card on the consumer
    QR page. Bug class: stale conditional field surfaces when parent context changes.
    Fix mechanism mirrors Standard Fix #5 (gate in hand-rolled get_events() dict).
    """

    def setUp(self):
        self.user = User.objects.create_user(email="bizleak@test.com", password="x")
        self.company = Company.objects.create(name="Biz Leak Farm")
        self.establishment = Establishment.objects.create(name="B1", company=self.company)
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
            transparency_score=0.0,
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

    def test_unit_preserved_when_credits_earned(self):
        """Carbon credits event with real earned amount: unit must surface (legitimate use)."""
        BusinessEvent.objects.create(
            history=self.history,
            type=BusinessEvent.CERTIFICATION,
            business_type="carbon_credits",
            carbon_credits_earned=5.0,
            carbon_credits_unit="tCO2e",
            date=timezone.now(),
        )
        events = self._public_business_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.get("carbon_credits_earned"), 5.0)
        self.assertEqual(ev.get("carbon_credits_unit"), "tCO2e")

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
        self.assertIsNone(ev.get("carbon_credits_earned"))
        self.assertIsNone(ev.get("carbon_credits_unit"))


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
        self.establishment = Establishment.objects.create(name="S1", company=self.company)
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
            transparency_score=0.0,
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

    def test_legitimate_seed_fields_still_present(self):
        """Sanity: stripping vendor data must not regress legitimate seed transparency."""
        event = self._public_planting_event()
        self.assertEqual(event.get("seed_lot_number"), "LOT-HASS-2025-09")
        self.assertEqual(event.get("seed_certification_status"), "organic")
        self.assertEqual(event.get("seed_treatment"), "untreated")


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
        self.establishment = Establishment.objects.create(name="X1", company=self.company)
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
            transparency_score=0.0,
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
        self.establishment = Establishment.objects.create(name="F20E", company=self.company)
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
            transparency_score=0.0,
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
        self.establishment = Establishment.objects.create(name="FPMOE", company=self.company)
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
            transparency_score=0.0,
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
            transparency_score=0.0,
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
        self.establishment = Establishment.objects.create(name="NT1", company=self.company)
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
            transparency_score=88.0,  # self-graded KPI — must be stripped for anonymous
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

    def test_transparency_score_stripped_for_anonymous(self):
        """The self-graded production score is a producer KPI; it must not ship to consumers."""
        self.assertNotIn(
            "transparency_score",
            self._anon_payload(),
            "self-graded transparency_score must not ship on the anonymous consumer payload (ECGT/FTC)",
        )

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
