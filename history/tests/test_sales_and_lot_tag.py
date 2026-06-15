"""
Tests for the SOE traceback sprint backend core:

- SalesRecord CRUD (owner-gated; "crop and quantity sold, date of sale,
  buyer" — the records inspectors verify at every annual inspection).
- Printable lot-tag PDF (§ 205.307 nonretail container identification):
  organic line ONLY when the lot-eligibility resolver passes.
- recent-inputs endpoint (distinct chemical products for form prefill).
"""

from datetime import timedelta
from io import BytesIO

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SalesRecord
from product.models import Parcel, Product
from users.models import User, WorksIn


class _Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email="owner@sales.test", password="x")
        self.outsider = User.objects.create_user(email="out@sales.test", password="x")
        self.company = Company.objects.create(name="Sales Farm Co")
        self.establishment = Establishment.objects.create(name="SE1", company=self.company)
        WorksIn.objects.create(user=self.owner, company=self.company, role="CA")
        self.parcel = Parcel.objects.create(name="SP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Sales Test Production",
            start_date=timezone.now() - timedelta(days=120),
            finish_date=timezone.now() - timedelta(days=10),
            lot_id="LOT-TEST-001",
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
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

    def _payload(self, **overrides):
        data = {
            "production_id": str(self.history.public_id),
            "sale_date": "2026-05-01",
            "buyer_name": "Coastal Wholesale",
            "quantity": "1200",
            "quantity_unit": "kg",
            "invoice_number": "INV-2026-001",
            "organic_on_invoice": True,
        }
        data.update(overrides)
        return data


class SalesRecordTests(_Base):
    def test_create_list_delete_roundtrip(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.post("/api/sales_records/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201)
        record_id = resp.json()["id"]

        resp = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["buyer_name"], "Coastal Wholesale")
        self.assertTrue(rows[0]["organic_on_invoice"])

        resp = self.client.delete(f"/api/sales_records/{record_id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(SalesRecord.objects.count(), 0)

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.post("/api/sales_records/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}")
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_denied(self):
        resp = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}")
        self.assertIn(resp.status_code, (401, 403))

    def test_unknown_production_404(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.post(
            "/api/sales_records/",
            self._payload(production_id="00000000-0000-0000-0000-000000000000"),
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_sales_never_in_public_payload(self):
        # Same policy as supplier fields: commercially sensitive, owner-only.
        SalesRecord.objects.create(
            production=self.history,
            sale_date="2026-05-01",
            buyer_name="Secret Buyer Inc",
            quantity=10,
            quantity_unit="kg",
        )
        import json as jsonlib

        from history.serializers import PublicHistorySerializer

        blob = jsonlib.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("Secret Buyer Inc", blob)
        self.assertNotIn("sales_records", blob)


class LotTagTests(_Base):
    def _pdf_text(self, content):
        return extract_text(BytesIO(content))

    def test_owner_gets_tag_pdf_with_lot(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        text = self._pdf_text(resp.content)
        self.assertIn("LOT LOT-TEST-001", text)
        self.assertIn("Sales Farm", text.replace("\n", " ")[:200] + text)

    def test_organic_line_only_when_lot_eligible(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            verification_status="verified",
            certification_scope="Crops",
            effective_date=(timezone.now() - timedelta(days=400)).date(),
            expiry_date=(timezone.now() + timedelta(days=200)).date(),
        )
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertIn("Certified organic by CCOF", self._pdf_text(resp.content))

        # Prohibited input on the lot -> organic line must disappear.
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.HERBICIDE,
            commercial_name="Glyphosate Pro",
            organic_approved="not_organic",
            date=timezone.now() - timedelta(days=30),
        )
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertNotIn("Certified organic", self._pdf_text(resp.content))

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertEqual(resp.status_code, 403)


class RecentInputsTests(_Base):
    def test_distinct_products_most_recent_first(self):
        for days_ago, name, status_value in [
            (40, "Neem Oil Pro", "omri_listed"),
            (20, "UAN-32", "not_organic"),
            (10, "Neem Oil Pro", "omri_listed"),  # duplicate, newer
        ]:
            ChemicalEvent.objects.create(
                history=self.history,
                type=ChemicalEvent.FERTILIZER,
                commercial_name=name,
                organic_approved=status_value,
                active_ingredient="azadirachtin" if "Neem" in name else "urea ammonium nitrate",
                date=timezone.now() - timedelta(days=days_ago),
            )
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/recent-inputs/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 200)
        products = resp.json()
        names = [p["commercial_name"] for p in products]
        self.assertEqual(names, ["Neem Oil Pro", "UAN-32"])
        self.assertEqual(products[0]["organic_approved"], "omri_listed")
        self.assertEqual(products[0]["active_ingredient"], "azadirachtin")

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/api/histories/recent-inputs/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 403)
