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

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import BusinessEvent, ChemicalEvent, History
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
