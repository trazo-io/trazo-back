"""
A5 — off-farm transport export (2026-06 NOP-alignment audit).

History.transport_method + destination were farmer-entered but never rendered in the
certifier PDF, so truck identity + receiving destination never reached the inspector.
These tests confirm the off-farm transport block renders them plus the new clean-transport
affidavit status (CCOF G6.1 / 7 CFR 205.272 / 205.307), flags a transfer with no affidavit,
and never leaks transport data to the consumer payload.
"""

import json

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History
from history.serializers import PublicHistorySerializer
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _section_text(elements):
    out = []
    for el in elements:
        text = getattr(el, "text", None)
        if text:
            out.append(text)
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                ctext = getattr(cell, "text", None)
                if ctext:
                    out.append(ctext)
    return " ".join(out)


class TransportExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="transport@test.com", password="x")
        self.company = Company.objects.create(name="Transport Farm")
        self.establishment = Establishment.objects.create(name="TE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="TP", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Transport Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=1000.0,
            production_unit="kg",
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
            sold_to="Korean Organic Buyer",
            transport_method="Refrigerated truck",
            destination="Sacramento Valley Packer",
            transport_vehicle_id="TRK-9921",
            transport_affidavit_on_file=False,
        )

    def _text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        return _section_text(svc._build_mass_balance_section())

    def test_transport_fields_render(self):
        text = self._text()
        self.assertIn("Off-Farm Transport", text)
        self.assertIn("Refrigerated truck", text)
        self.assertIn("Sacramento Valley Packer", text)
        self.assertIn("TRK-9921", text)

    def test_missing_affidavit_fires_review(self):
        self.assertIn("[REVIEW] 7 CFR 205.272", self._text())

    def test_affidavit_on_file_no_review(self):
        self.history.transport_affidavit_on_file = True
        self.history.save(update_fields=["transport_affidavit_on_file"])
        # Mirror of test_missing_affidavit_fires_review: assert the TRANSPORT review is
        # gone, not that the whole section is review-free. This asserted a bare "[REVIEW]"
        # and so was failing on the mass-balance and output-reconciliation reviews the same
        # section legitimately raises for a fixture with no purchase quantities and no
        # quantity sold — neither has anything to do with a clean-transport affidavit.
        # (Pre-existing failure, present in the 2026-08-10 baseline; corrected same day.)
        self.assertNotIn("[REVIEW] 7 CFR 205.272", self._text())

    def test_transport_data_not_leaked_to_consumer(self):
        data = PublicHistorySerializer(self.history).data
        # New clean-truck fields are not even on the consumer serializer.
        self.assertNotIn("transport_affidavit_on_file", data)
        self.assertNotIn("transport_vehicle_id", data)
        # transport_method / destination are owner-only -> stripped for the anonymous payload.
        self.assertNotIn("transport_method", data)
        self.assertNotIn("destination", data)
        blob = json.dumps(data, default=str)
        self.assertNotIn("TRK-9921", blob, "transport vehicle id leaked to consumer payload")
