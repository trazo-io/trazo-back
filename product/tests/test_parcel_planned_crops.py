"""The crops a parcel grows now or is planned to grow, with acres (2026-11-11).

CCOF ORGB49 (R11 3/14/2022) A7 "Parcel acreage (total acres to be certified organic at this location)" and A8
"List crops currently grown (or planned to be grown) on this parcel, and the acreage for each crop"; WSDA AGR
2264 (R 05/26) ref 8 crop (varieties), estimated harvest date and acres per crop, plus total site acreage; OTCO
C2 (2024/06/05) 2.1 9) total acres and 10) crops with acres. Until this slice no per-crop acreage existed: a
multi-crop parcel could not be split, and the total printed only as the drawn area under the map.
"""

import io
from datetime import date

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelPlannedCrop, Product
from users.models import User, WorksIn

CCOF = "California Certified Organic Farmers (CCOF)"
WSDA = "Washington State Department of Agriculture (WSDA)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Parcel(TestCase):
    certifier = WSDA

    def setUp(self):
        self.company = Company.objects.create(name="Squilchuck LLC")
        self.user = User.objects.create_user(email="crops@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Squilchuck Farm", company=self.company, state="WA")
        self.other_est = Establishment.objects.create(name="Second Farm", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=self.certifier
        )
        # 8.0 ha = 19.8 acres.
        self.parcel = Parcel.objects.create(
            name="Upper Bench", establishment=self.est, area=8.0, application_answers={"currently_certified": "no"}
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, suffix="", parcel=None, est=None):
        parcel = parcel or self.parcel
        est = est or self.est
        return f"/api/companies/{self.company.id}/establishments/{est.id}/parcels/{parcel.id}/planned-crops/{suffix}"

    def crop(self, **kw):
        return ParcelPlannedCrop.objects.create(parcel=self.parcel, **{"crop": "Apples", **kw})

    def answer(self, **answers):
        self.parcel.application_answers = {**self.parcel.application_answers, **answers}
        self.parcel.save(update_fields=["application_answers"])

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))

    def row(self, agent, document_id, ref):
        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)


class TheApiKeepsTheRows(_Parcel):
    def test_add_edit_and_remove_a_crop(self):
        r = self.client.post(
            self.url(),
            {"crop": "  Apples ", "variety": "Honeycrisp", "expected_harvest": "2027-09-01", "acres": "12.5"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        crop = ParcelPlannedCrop.objects.get()
        self.assertEqual((crop.parcel, crop.crop, str(crop.acres)), (self.parcel, "Apples", "12.50"))
        r = self.client.patch(self.url(f"{crop.id}/"), {"acres": "", "expected_harvest": ""}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        crop.refresh_from_db()
        self.assertIsNone(crop.acres)
        self.assertIsNone(crop.expected_harvest)
        self.assertEqual(self.client.delete(self.url(f"{crop.id}/")).status_code, 204)
        self.assertFalse(ParcelPlannedCrop.objects.exists())

    def test_a_blank_crop_or_a_zero_acreage_is_refused(self):
        self.assertEqual(self.client.post(self.url(), {"crop": "  "}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url(), {"crop": "Pears", "acres": "0"}, format="json").status_code, 400)

    def test_a_parcel_in_the_body_cannot_move_the_row(self):
        theirs = Parcel.objects.create(name="Elsewhere", establishment=self.other_est, area=1.0)
        r = self.client.post(self.url(), {"crop": "Pears", "parcel": theirs.id}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(ParcelPlannedCrop.objects.get().parcel, self.parcel)

    def test_the_wizard_payload_carries_the_rows_and_the_open_season_crops(self):
        self.crop(acres=3)
        History.objects.create(
            name="Pears 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Pears"),
            start_date=timezone.now(),
        )
        r = self.client.get(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/parcels/{self.parcel.id}/application/"
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c["crop"] for c in r.json()["planned_crops"]], ["Apples"])
        self.assertEqual(r.json()["open_season_crops"], ["Pears"])


class PlannedCropTenancyTests(_Parcel):
    def test_another_company_reaches_nothing(self):
        crop = self.crop(acres=3)
        outsider = User.objects.create_user(email="other@crops.test", password="x")
        WorksIn.objects.create(user=outsider, company=Company.objects.create(name="Other"), role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.get(self.url(f"{crop.id}/")).status_code, (403, 404))
        r = self.client.patch(self.url(f"{crop.id}/"), {"crop": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        self.assertIn(self.client.post(self.url(), {"crop": "Mine"}, format="json").status_code, (403, 404))
        crop.refresh_from_db()
        self.assertEqual(crop.crop, "Apples")
        self.assertEqual(ParcelPlannedCrop.objects.count(), 1)

    def test_another_farms_parcel_reads_like_a_missing_one(self):
        theirs = Parcel.objects.create(name="Elsewhere", establishment=self.other_est, area=1.0)
        foreign = self.client.post(self.url(parcel=theirs), {"crop": "Pears"}, format="json")
        missing = self.client.post(self.url(parcel=Parcel(pk=999999)), {"crop": "Pears"}, format="json")
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(foreign.json(), missing.json())
        self.assertFalse(ParcelPlannedCrop.objects.exists())


class TheTablePrintsInSectionA(_Parcel):
    def test_each_column_prints_and_a_blank_one_says_so(self):
        self.crop(variety="Honeycrisp", expected_harvest=date(2027, 9, 1), acres=12.5)
        self.crop(crop="Pears")
        page = self.page()
        # The table's cells, read back column by column by the text extractor.
        for words in ("Crop", "Variety", "Expected harvest", "Apples", "Honeycrisp", "2027-09-01", "12.5 ", "Pears"):
            self.assertIn(words, page)
        self.assertNotIn("12.50", page)
        self.assertIn("[REVIEW] No acres are given for: Pears.", page)
        self.assertIn("Acres listed: 12.5 across 1 crop.", page)
        self.assertIn("Parcel area on file: 19.8 acres (8.00 ha).", page)

    def test_an_empty_table_says_so(self):
        self.assertIn("No crop is listed for this parcel.", self.page())

    def test_acres_to_certify_prints_and_figures_that_disagree_are_named(self):
        self.answer(acres_to_certify="10")
        self.crop(acres=12.5)
        page = self.page()
        self.assertIn("Total acres on this parcel to be certified organic 10", page)
        # A double crop lists the same ground twice: stated, never a review line.
        self.assertIn("The crops listed add up to 12.5 acres against 10 acres to be certified", page)
        self.assertNotIn("[REVIEW] The crops listed", page)
        self.answer(acres_to_certify="25")
        self.assertIn(
            "[REVIEW] The acres to be certified (25) are more than the parcel area on file (19.8 acres).", self.page()
        )

    def test_an_open_season_the_list_leaves_out_is_named(self):
        History.objects.create(
            name="Pears 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Pears"),
            start_date=timezone.now(),
        )
        self.crop(crop="Apples", acres=4)
        self.assertIn("[REVIEW] Seasons open on this parcel grow a crop the list does not name: Pears.", self.page())
        self.crop(crop="Bartlett pears", acres=4)
        self.assertNotIn("Seasons open on this parcel grow a crop", self.page())


class TheRegisterReadsTheTable(_Parcel):
    def test_the_crop_rows_are_open_until_a_crop_is_listed(self):
        self.assertTrue(self.row("wsda", "AGR 2264", "8").is_open)
        self.answer(acres_to_certify="18")
        self.crop(acres=18)
        self.assertEqual(self.row("wsda", "AGR 2264", "8").state, "answered")

    def test_ccof_a7_a8_and_otco_2_1_9_2_1_10(self):
        self.answer(acres_to_certify="18")
        self.crop(acres=18)
        self.osp.certifier_name = CCOF
        self.osp.save(update_fields=["certifier_name"])
        self.assertEqual(self.row("ccof", "ORGB49", "A7").state, "answered")
        self.assertEqual(self.row("ccof", "ORGB49", "A8").state, "answered")
        self.osp.certifier_name = OTCO
        self.osp.save(update_fields=["certifier_name"])
        self.assertEqual(self.row("otco", "C2", "2.1-9").state, "answered")
        self.assertEqual(self.row("otco", "C2", "2.1-10").state, "answered")
