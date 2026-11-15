"""What a previous manager states on their affidavit, printed on the parcel page (2026-11-11).

CCOF ORGB49 (R11 3/14/2022) Affidavit of Land History B ("I have this knowledge because: I owned / I managed /
Other"), C (Name, Title, Company, Email, Phone) and D (Full Product Name, Full Manufacturer Name, Application
Date(s), Type). WSDA AGR 2262 (R 12/19) 1 site name as the signer references it, 3 acreage, 5a(i) date of the
signer's last organic inspection, 5b acres remaining on the signer's certificate, 6 and 6a treated seed planted
under the signer's management with brand and date, 7 dates produced and acreage, 8 materials with dates, and
the attestation's email. The parcel page printed a count of rows for each affidavit and nothing the signer said.
"""

import io
from datetime import date

from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import LandownerAffidavit, OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from product.models import Parcel
from users.models import User, WorksIn


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Parcel(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Wenatchee Heights LLC")
        self.user = User.objects.create_user(email="affidavit@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Wenatchee Heights", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name="Washington State Department of Agriculture (WSDA)",
        )
        self.parcel = Parcel.objects.create(
            name="Fuji Blocks", establishment=self.est, area=6.0, application_answers={"currently_certified": "no"}
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, suffix=""):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/affidavits/{suffix}"

    def post(self, **data):
        return self.client.post(
            self.url(), {"parcel": self.parcel.id, "previous_manager_name": "Dale Ruiz", **data}, format="json"
        )

    def affidavit(self, **kw):
        return LandownerAffidavit.objects.create(parcel=self.parcel, previous_manager_name="Dale Ruiz", **kw)

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))


class TheApiKeepsWhatTheSignerStated(_Parcel):
    def test_signer_and_site_fields_round_trip(self):
        r = self.post(
            signer_basis="managed",
            signer_title="Orchard manager",
            signer_company="Ruiz Orchards",
            signer_email="dale@ruiz.example",
            last_inspection_date="2025-08-14",
            portion_remains="yes",
            acres_remaining="4.5",
            treated_seed_planted="yes",
            treated_seed_detail="Apron XL, planted 2024-04-02",
        )
        self.assertEqual(r.status_code, 201, r.content)
        a = LandownerAffidavit.objects.get()
        self.assertEqual(
            (a.signer_basis, a.signer_email, str(a.acres_remaining)), ("managed", "dale@ruiz.example", "4.50")
        )
        self.assertEqual(a.last_inspection_date, date(2025, 8, 14))

    def test_a_detail_under_an_answer_that_does_not_ask_for_it_is_dropped(self):
        r = self.post(
            signer_basis="owned",
            signer_basis_other="leftover",
            portion_remains="no",
            acres_remaining="4.5",
            treated_seed_planted="no",
            treated_seed_detail="leftover",
        )
        self.assertEqual(r.status_code, 201, r.content)
        a = LandownerAffidavit.objects.get()
        self.assertEqual((a.signer_basis_other, a.acres_remaining, a.treated_seed_detail), ("", None, ""))

    def test_rows_take_a_type_months_and_acres_and_refuse_malformed_ones(self):
        good = [
            {
                "year": 2024,
                "land_use": "Apples",
                "inputs": "Surround WP",
                "manufacturer": "Tessenderlo Kerley",
                "date_applied": "2024-06-12",
                "material_type": "pest_disease_control",
                "period_from": "2024-03",
                "period_to": "2024-10",
                "acres": "6",
            }
        ]
        self.assertEqual(self.post(yearly_history=good).status_code, 201)
        for bad in (
            {"material_type": "fungicide-ish"},
            {"period_from": "03/2024"},
            {"period_from": "2024-10", "period_to": "2024-03"},
            {"acres": "6,5"},
            {"acres": "0"},
        ):
            r = self.post(yearly_history=[{"year": 2024, **bad}])
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(LandownerAffidavit.objects.count(), 1)


class TheParcelPagePrintsIt(_Parcel):
    def test_the_signer_lines_print_under_the_manager_table(self):
        self.affidavit(
            field_name="Fuji Blocks 28-35",
            field_acres=6,
            signer_basis="managed",
            signer_title="Orchard manager",
            signer_company="Ruiz Orchards",
            signer_email="dale@ruiz.example",
            previous_manager_phone="509-555-0199",
            last_inspection_date=date(2025, 8, 14),
            portion_remains="yes",
            acres_remaining=4.5,
            treated_seed_planted="no",
        )
        page = self.page()
        for words in (
            "Stated by Dale Ruiz:",
            "Knows the parcel's history because they managed the parcel and controlled activities there.",
            "Signer: Dale Ruiz, Orchard manager, Ruiz Orchards; dale@ruiz.example; 509-555-0199.",
            "Site as the signer names it: Fuji Blocks 28-35.",
            "Site acreage stated by the signer: 6 acres.",
            "Signer's last organic inspection of the site: 2025-08-14.",
            "A portion of the site remains on the signer's certificate: 4.5 acres.",
            "No treated seed was planted during the signer's management (stated).",
        ):
            self.assertIn(words, page)

    def test_a_phone_never_stands_in_for_the_signers_name(self):
        from certifications.services.parcel_land_history import affidavit_signer_lines

        a = LandownerAffidavit(previous_manager_name="", previous_manager_phone="(509) 555-0188")
        self.assertEqual(affidavit_signer_lines(a), ["Signer's contact: (509) 555-0188."])
        a = LandownerAffidavit(
            previous_manager_name="", signer_company="Sample Ridge Orchard Co.", previous_manager_phone="(509) 555-0188"
        )
        self.assertEqual(
            affidavit_signer_lines(a), ["Signer: Sample Ridge Orchard Co.", "Signer's contact: (509) 555-0188."]
        )
        a = LandownerAffidavit(previous_manager_name="Dale Ruiz", previous_manager_phone="(509) 555-0188")
        self.assertEqual(affidavit_signer_lines(a), ["Signer: Dale Ruiz; (509) 555-0188."])

    def test_treated_seed_in_the_signers_period_is_a_review_line(self):
        self.affidavit(treated_seed_planted="yes")
        self.assertIn(
            "[REVIEW] Treated seed was planted during the signer's management: no treatment brand or planting "
            "date given.",
            self.page(),
        )

    def test_the_signers_materials_table_prints_with_type_months_and_acres(self):
        self.affidavit(
            yearly_history=[
                {
                    "year": 2024,
                    "land_use": "Apples",
                    "inputs": "Surround WP",
                    "manufacturer": "Tessenderlo Kerley",
                    "date_applied": "2024-06-12",
                    "material_type": "pest_disease_control",
                    "period_from": "2024-03",
                    "period_to": "2024-10",
                    "acres": "6",
                }
            ]
        )
        page = self.page()
        for words in (
            "Year",
            "Manufacturer",
            "Type",
            "Surround WP",
            "Tessenderlo Kerley",
            "2024-06-12",
            "03/2024 to 10/2024",
            "Pest or disease control",
        ):
            self.assertIn(words, page)

    def test_an_affidavit_with_nothing_stated_prints_no_stated_block(self):
        self.affidavit()
        self.assertNotIn("Stated by Dale Ruiz", self.page())


class ReviewFindingsOn394(_Parcel):
    def test_a_json_array_body_is_a_400_on_each_route_that_coerces_blanks(self):
        # A list has .copy() too; its .get() raised a 500 where DRF answers a non-object body with a 400.

        self.assertEqual(self.client.post(self.url(), [{"x": 1}], format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/parcel-crop-history/", [{"x": 1}], format="json").status_code, 400)
        planned = (
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/parcels/{self.parcel.id}/planned-crops/"
        )
        self.assertEqual(self.client.post(planned, [{"x": 1}], format="json").status_code, 400)

    def test_non_finite_acres_are_refused(self):
        for value in ("NaN", "Infinity", "-Infinity", "inf"):
            r = self.post(yearly_history=[{"year": 2024, "acres": value}])
            self.assertEqual(r.status_code, 400, value)
        self.assertFalse(LandownerAffidavit.objects.exists())
