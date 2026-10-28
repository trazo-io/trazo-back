"""Who identified a pest is the farm's statement, not a credential (Astra follow-up 2026-10-28, B2).

The live audit saved a pest identification with "Agrónomo" picked in the form and read it back as
"Licensed Agronomist" / "Agrónomo matriculado" on the producer detail AND on the buyer preview.
"Licensed" asserts a credential the form never asked about and the record does not establish;
WA (Commercial Pest Control Consultant), OR (Pesticide Consultant), CA (Pest Control Adviser) and
the ASA Certified Crop Adviser are distinct things no role name can stand for.

Oscar's decision: the labels name a role with no credential, and the field is producer/certifier
only. The buyer page keeps the plain fact that a pest was identified.
"""

import csv
import io
import json

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from company.models import Company, Establishment
from history.models import History, PestManagementEvent
from history.serializers import PublicHistorySerializer
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

NEUTRAL_LABELS = {
    "farmer": "Farmer or farm staff",
    "agronomist": "Agronomist",
    "entomologist": "Entomologist",
    "extension_service": "Extension adviser",
    "crop_consultant": "Crop advisor",
    "lab": "Laboratory report",
}

CREDENTIAL_WORDS = ("licensed", "certified", "accredited", "verified", "registered")


class IdentifierLabelsNameARoleNotACredential(SimpleTestCase):
    def test_the_labels_are_the_neutral_roles(self):
        self.assertEqual(dict(PestManagementEvent.IDENTIFIED_BY_CHOICES), NEUTRAL_LABELS)

    def test_no_label_claims_a_credential(self):
        for value, label in PestManagementEvent.IDENTIFIED_BY_CHOICES:
            for word in CREDENTIAL_WORDS:
                self.assertNotIn(word, label.lower(), f"{value} reads as a credential: {label!r}")

    def test_the_help_text_says_it_is_the_farms_statement(self):
        help_text = PestManagementEvent._meta.get_field("identified_by").help_text
        self.assertIn("farm's statement", help_text)
        self.assertIn("does not verify", help_text)


class IdentifierIsProducerAndCertifierOnly(TestCase):
    def setUp(self):
        cache.clear()  # public-endpoint throttle counters live in the shared cache
        self.user = User.objects.create_user(email="pestid@test.com", password="x")
        self.company = Company.objects.create(name="Identifier Farm")
        establishment = Establishment.objects.create(name="ID1", company=self.company, state="WA")
        self.history = History.objects.create(
            name="Gala 2026",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apples"),
            parcel=Parcel.objects.create(name="Block 7", establishment=establishment, area=4.0),
            operator=self.user,
            published=True,
        )
        self.event = PestManagementEvent.objects.create(
            history=self.history,
            type="PI",
            date=timezone.now(),
            description="Aphid identification",
            pest_species="Rosy apple aphid",
            identified_by="agronomist",
        )

    def _events(self, data):
        return data.get("events") or []

    def _pest_event(self, data):
        rows = [e for e in self._events(data) if e.get("pest_species") == "Rosy apple aphid"]
        self.assertEqual(len(rows), 1, "the pest record is missing from the payload, so nothing was checked")
        return rows[0]

    def test_absent_from_the_anonymous_payload(self):
        event = self._pest_event(PublicHistorySerializer(self.history).data)
        self.assertNotIn("identified_by", event)
        self.assertNotIn("identified_by", event.get("extra_data") or {})

    def test_absent_from_the_buyer_page_endpoint(self):
        resp = self.client.get(
            reverse("production-transparency-detail", kwargs={"production_public_id": str(self.history.public_id)})
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        blob = resp.content.decode()
        self.assertIn("Rosy apple aphid", blob, "the pest record is not on the buyer payload at all")
        self.assertNotIn('"identified_by"', blob)

    def test_present_for_the_owner(self):
        self.user.companies.add(self.company)
        request = APIRequestFactory().get("/")
        request.user = self.user
        data = PublicHistorySerializer(self.history, context={"request": request}).data
        self.assertEqual(self._pest_event(data).get("identified_by"), "agronomist")

    def test_the_owner_previewing_the_buyer_view_does_not_get_it(self):
        self.user.companies.add(self.company)
        request = APIRequestFactory().get("/")
        request.user = self.user
        data = PublicHistorySerializer(self.history, context={"request": request, "force_public_view": True}).data
        self.assertNotIn("identified_by", json.dumps(self._pest_event(data)))

    def test_the_certifier_csv_prints_the_neutral_label(self):
        text = AuditExportService(self.history, certification_type="organic").generate_csv().getvalue()
        text = text.decode("utf-8-sig") if isinstance(text, bytes) else text
        rows = [" ".join(r) for r in csv.reader(io.StringIO(text))]
        hits = [r for r in rows if "ID by:" in r]
        self.assertTrue(hits, "the CSV carried no identifier at all, so nothing was checked")
        self.assertTrue(any("ID by: Agronomist" in r for r in hits), hits)
        self.assertFalse(any("Licensed" in r for r in hits), hits)
