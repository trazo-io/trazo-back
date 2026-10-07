"""The buyer page states the record (recordkeeping review S6, 2026-10-07: F-09, F-11, F-25).

F-09: the chip for a grower's own dropdown pick read "Organic-approved · grower-reported", a
verdict word leading an answer nobody but the grower had given; and for two inputs that carried
a National List substance on an unconfirmed basis the tooltip said Trazo had found nothing.
F-11: a checkbox ticked at company sign-up ("Soil Health Focus", "Clean Energy Use") was served
as `farm_context.company_sustainability.goals` and printed as a public "Sustainability
Commitment" list. F-25: "Purchased OMRI compost ([supplier withheld])" on the farm profile, and
"Tangent, -" for a location with no country.

Each test here went red on the code before the fix, on an assertion.
"""

import json
from datetime import timedelta

from django.utils import timezone

from rest_framework.test import APITestCase

from certifications.models import NationalListSubstance
from common.location import city_state_label, joined_parts
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.claim_authority import LABEL_INPUT_GROWER_REPORTED
from history.services.claim_resolver import resolve_input_status
from history.services.privacy import redact_supplier_names
from product.models import Parcel, Product
from users.models import User


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class BuyerPageStatesTheRecordTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="states-record@test.com", password="x")
        cls.company = Company.objects.create(
            name="Record Co",
            sustainability_metadata={"sustainability_goals": ["soil_health", "renewable_energy"]},
        )
        cls.establishment = Establishment.objects.create(
            name="Record Farm", company=cls.company, city="Tangent", state="OR", country=None
        )
        cls.parcel = Parcel.objects.create(name="Home Field", establishment=cls.establishment, area=5.0)
        cls.product = Product.objects.create(name="Blueberries")
        cls.history = History.objects.create(
            name="Blueberries 2026",
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
            product=cls.product,
            parcel=cls.parcel,
            operator=cls.user,
            earning=0.0,
            production_amount=1000,
            production_unit="lb",
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        cls.lime_sulfur = NationalListSubstance.objects.create(
            substance_name="Lime sulfur", cfr_section="205.601", status="allowed"
        )

    def _event(self, **kwargs):
        return ChemicalEvent.objects.create(
            history=self.history, created_by=self.user, description="spray", date=timezone.now(), **kwargs
        )

    # -- F-09: the chip is a record, not a verdict ---------------------------------------

    def test_the_grower_chip_is_worded_as_a_record(self):
        self.assertEqual(LABEL_INPUT_GROWER_REPORTED, "Recorded by the farm as allowed for organic use")
        status = resolve_input_status(
            self._event(commercial_name="Rex Lime Sulfur", organic_approved="certifier_approved")
        )
        self.assertEqual(status["status"], "organic_approved")
        self.assertFalse(status["label"].lower().startswith("organic-approved"), status["label"])

    def test_an_unconfirmed_national_list_link_is_named_in_the_status(self):
        event = self._event(commercial_name="Rex Lime Sulfur", organic_approved="certifier_approved")
        ChemicalEvent.objects.filter(pk=event.pk).update(
            national_list_substance=self.lime_sulfur, national_list_basis="legacy_unverified"
        )
        event.refresh_from_db()
        status = resolve_input_status(event)
        self.assertEqual(status["status"], "organic_approved", "an unconfirmed basis is not evidence for the chip")
        link = status.get("national_list_link") or {}
        self.assertEqual(link.get("basis"), "not_confirmed")
        self.assertEqual(link.get("substance"), "Lime sulfur")
        self.assertEqual(link.get("cfr_section"), "205.601")

    def test_a_record_with_no_link_carries_none(self):
        status = resolve_input_status(self._event(commercial_name="Entrust SC", organic_approved="certifier_approved"))
        self.assertNotIn("national_list_link", status)

    # -- F-11: sign-up goals are not a public claim --------------------------------------

    def test_the_public_payload_carries_no_sign_up_goals(self):
        response = self.client.get(f"/api/transparency/{self.history.public_id}/")
        self.assertEqual(response.status_code, 200, response.content[:300])
        payload = response.json()
        sustainability = (payload.get("farm_context") or {}).get("company_sustainability") or {}
        self.assertNotIn("goals", sustainability)
        text = response.content.decode()
        for label in ("Soil Health Focus", "Renewable Energy Use", "soil_health", "renewable_energy"):
            self.assertNotIn(label, text)

    # -- F-25: the profile list and the location line ------------------------------------

    def test_a_supplier_aside_is_dropped_from_a_profile_list_entry(self):
        result = redact_supplier_names(
            ["Purchased OMRI compost (Rexius)", "Seed came from Rexius this year", "Winter cover crops"],
            {"Rexius"},
        )
        self.assertEqual(result[0], "Purchased OMRI compost")
        self.assertEqual(result[1], "Seed came from [supplier withheld] this year", "prose keeps the placeholder")
        self.assertEqual(result[2], "Winter cover crops")
        # The live column holds the list JSON-encoded; the same rule applies to that string.
        encoded = redact_supplier_names('["Purchased OMRI compost (Rexius)", "Winter cover crops"]', {"Rexius"})
        self.assertEqual(json.loads(encoded), ["Purchased OMRI compost", "Winter cover crops"])

    def test_the_location_line_prints_only_recorded_parts(self):
        self.assertEqual(self.establishment.get_location(), "Tangent, OR")
        self.assertEqual(city_state_label(_Obj(city="Tangent", state="-")), "Tangent")
        self.assertEqual(city_state_label(_Obj(city="", state="OR")), "OR")
        self.assertIsNone(city_state_label(_Obj(city="", state="")))
        self.assertEqual(
            joined_parts(_Obj(city="Tangent", state="OR", country="US"), ("city", "state", "country")),
            "Tangent, OR, US",
        )

    def test_the_public_location_has_no_placeholder(self):
        Establishment.objects.filter(pk=self.establishment.pk).update(state="-")
        try:
            response = self.client.get(f"/api/transparency/{self.history.public_id}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["farmer"]["location"], "Tangent")
        finally:
            Establishment.objects.filter(pk=self.establishment.pk).update(state="OR")
