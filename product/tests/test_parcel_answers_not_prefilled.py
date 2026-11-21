"""A new parcel holds no answer the operator did not give (first-run audit, 2026-11-21).

A first run as a new grower found the parcel application's "Is this parcel container or greenhouse production?"
and "Is treated lumber in contact with crops or soil?" already answered "No" on a parcel nobody had opened, and the
renewal packet printed "No" for each. Both were non-null BooleanFields with default=False, and the app's create call
sent treated_lumber_present='false' on every new parcel. A default is a claim: unanswered is now null.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from product.models import Parcel
from product.services.parcel_application_status import parcel_application_values
from users.models import User, WorksIn


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class ParcelAnswersNotPrefilledTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Sample Ridge Orchards")
        self.user = User.objects.create_user(email="ridge@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Sample Ridge", company=self.company, state="WA")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _application_url(self, parcel):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/parcels/{parcel.id}/application/"

    def test_a_new_parcel_has_neither_answer(self):
        parcel = Parcel.objects.create(name="Block B", establishment=self.est, area=15.0)
        parcel.refresh_from_db()
        self.assertIsNone(parcel.treated_lumber_present)
        self.assertIsNone(parcel.container_production)
        values = parcel_application_values(parcel)
        self.assertIn("treated_lumber_present", values, "premise: the bound value is served")
        self.assertIsNone(values["treated_lumber_present"])
        self.assertIsNone(values["container_production"])

    def test_a_parcel_created_through_the_api_without_the_keys_stays_unanswered(self):
        # The app sends multipart; DRF reads a missing boolean in form data as False unless the field allows null.
        from subscriptions.models import Plan, Subscription

        plan, _ = Plan.objects.update_or_create(
            slug="test-unlimited",
            defaults={
                "name": "t",
                "description": "t",
                "price": 0,
                "interval": "monthly",
                "features": {"max_parcels_per_establishment": -1},
                "is_active": True,
            },
        )
        Subscription.objects.create(company=self.company, plan=plan, status="active")
        r = self.client.post(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/parcels/",
            {"name": "Block C", "establishment": self.est.id, "area": "10", "polygon": "[]", "map_metadata": "{}"},
            format="multipart",
        )
        self.assertIn(r.status_code, (200, 201), getattr(r, "data", r))
        parcel = Parcel.objects.get(establishment=self.est, name="Block C")
        self.assertIsNone(parcel.treated_lumber_present)
        self.assertIsNone(parcel.container_production)

    def test_the_application_stores_an_answer_and_can_clear_it(self):
        parcel = Parcel.objects.create(name="Block A", establishment=self.est, area=15.0)
        r = self.client.put(
            self._application_url(parcel),
            {"values": {"treated_lumber_present": False, "container_production": False}},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        parcel.refresh_from_db()
        self.assertIs(parcel.treated_lumber_present, False)
        self.assertIs(parcel.container_production, False)
        r = self.client.put(self._application_url(parcel), {"values": {"treated_lumber_present": None}}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        parcel.refresh_from_db()
        self.assertIsNone(parcel.treated_lumber_present)
        self.assertIs(parcel.container_production, False)

    def test_the_parcel_page_prints_not_answered_instead_of_no(self):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            certifier_name="Washington State Department of Agriculture",
        )
        parcel = Parcel.objects.create(name="Block B", establishment=self.est, area=15.0)
        text = _text(generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=parcel))
        question = "Is treated lumber in contact with crops or soil?"
        self.assertIn(question, text, "premise: the question is printed")
        after = text.split(question, 1)[1][:60]
        self.assertNotRegex(after, r"^\s*No\b", after)
        self.assertRegex(after, r"^\s*Not (yet )?answered", after)

        parcel.treated_lumber_present = False
        parcel.save(update_fields=["treated_lumber_present"])
        text = _text(generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=parcel))
        self.assertRegex(text.split(question, 1)[1][:60], r"^\s*No\b", "premise: an answered No still prints No")


class ReviewOfBack512Tests(TestCase):
    """The independent review of back #512."""

    def setUp(self):
        self.company = Company.objects.create(name="Sample Ridge Orchards")
        self.user = User.objects.create_user(email="ridge512@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Sample Ridge", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="Block B", establishment=self.est, area=15.0)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = (
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/parcels/{self.parcel.id}/application/"
        )

    def test_an_unanswered_statement_keeps_the_application_open(self):
        from product.services.parcel_application_status import parcel_application_status

        self.assertIn("site_statements", parcel_application_status(self.parcel)["missing"])
        self.parcel.treated_lumber_present = False
        self.parcel.save(update_fields=["treated_lumber_present"])
        self.assertIn("site_statements", parcel_application_status(self.parcel)["missing"], "container still open")
        self.parcel.container_production = False
        self.parcel.save(update_fields=["container_production"])
        self.assertNotIn("site_statements", parcel_application_status(self.parcel)["missing"])

    def test_an_empty_or_null_string_clears_instead_of_answering_no(self):
        self.parcel.treated_lumber_present = True
        self.parcel.save(update_fields=["treated_lumber_present"])
        for blank in ("", "null"):
            r = self.client.put(self.url, {"values": {"treated_lumber_present": blank}}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            self.parcel.refresh_from_db()
            self.assertIsNone(self.parcel.treated_lumber_present, blank)
            self.parcel.treated_lumber_present = True
            self.parcel.save(update_fields=["treated_lumber_present"])
        r = self.client.put(self.url, {"values": {"treated_lumber_present": "false"}}, format="json")
        self.parcel.refresh_from_db()
        self.assertIs(self.parcel.treated_lumber_present, False, "premise: a real No is still stored")

    def test_null_for_a_column_that_cannot_hold_it_is_refused(self):
        self.client.raise_request_exception = False  # a crash reads as a 500 response, not a test error
        r = self.client.put(self.url, {"values": {"parcel_name": None}}, format="json")
        self.assertEqual(r.status_code, 400, getattr(r, "data", r))
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.name, "Block B")

    def test_an_installation_answer_counts_only_under_an_answered_no(self):
        from certifications.services.parcel_map_elements import _treated_lumber

        self.assertTrue(
            _treated_lumber({"treated_lumber_present": False, "treated_lumber_noncontact_present": True}, None)
        )
        self.assertFalse(
            _treated_lumber({"treated_lumber_present": None, "treated_lumber_noncontact_present": True}, None)
        )
        self.assertTrue(_treated_lumber({"treated_lumber_present": True}, None))
