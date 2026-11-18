"""CCOF Grower Materials Application ORGB41: the preamble, §A and §B (2026-11-17).

What the register held open, re-read against the code first (status had printed since 2026-11-04):

* "Only materials included in your OSP Materials List may be used." The input and amendment forms took the
  product name as free text. `productions/plan-materials/` now offers the plan's own materials beside the
  name; a material no longer used, and one the list must not hold, are not offered.
* §A/§B ask the full product name, the manufacturer and the reason for use of every row, and each agent asks
  whether it is in use or intended. A missing cell printed as missing; nothing found it before filing. The
  plan review now lists each row and its blank cells (`materials_rows_incomplete`).
* A row with no reason printed the record's kind ("Pest control") in the reason column, where it read as the
  operator's answer. The cell is left blank and the kind is in the comments, labelled as the records'; the
  editor shows it as a hint.
* "List all materials used or planned for use": the editor offers "in use" for a row the records show applied.
"""

from datetime import date, datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.plan_materials import incomplete_rows, materials_list_rows, plan_materials
from certifications.services.plan_review import plan_review
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel
from users.models import User, WorksIn


class _Orchard(TestCase):
    def setUp(self):
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())
        self.company = Company.objects.create(name="Yakima Bench Orchards LLC")
        self.owner = User.objects.create_user(email="bench@test.com", password="x")
        WorksIn.objects.create(user=self.owner, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Yakima Bench", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="Fuji Block", establishment=self.est, area=8.0)
        self.history = Production.objects.create(name="Fuji 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")

    def entry(self, name, **fields):
        return PlanMaterialEntry.objects.create(osp=self.osp, product_name=name, **fields)


class IncompleteRowsAreListedBeforeFiling(_Orchard):
    def test_a_row_missing_its_maker_and_reason_is_listed_with_both(self):
        self.entry("Kocide 3000-O", category="pest_disease_weed", status="in_use")
        (line,) = incomplete_rows(self.osp)
        self.assertTrue(line.startswith("Kocide 3000-O ("), line)
        self.assertTrue(line.endswith("manufacturer, reason for use not stated"), line)

    def test_a_complete_row_and_one_no_longer_used_are_not_listed(self):
        self.entry("Kocide 3000-O", manufacturer="Certis Biologicals", reason_for_use="Fire blight", status="in_use")
        self.entry("Old Fish Blend", status="discontinued")
        self.assertEqual(incomplete_rows(self.osp), [])

    def test_a_bare_national_list_substance_needs_its_brand(self):
        self.osp.approved_national_list_substances.add(
            NationalListSubstance.objects.get(substance_name="Elemental sulfur")
        )
        (line,) = incomplete_rows(self.osp)
        self.assertIn("brand and formulation, manufacturer, reason for use, in use or intended for use", line)

    def test_the_plan_review_lists_them_on_the_materials_application(self):
        self.entry("Kocide 3000-O", status="in_use")
        findings = {f.code: f for f in plan_review(self.osp, reference=timezone.now()).findings}
        self.assertIn("materials_rows_incomplete", findings)
        finding = findings["materials_rows_incomplete"]
        self.assertEqual(finding.module_key, "materials_application")
        self.assertEqual(finding.count, 1)


class TheEditorSaysWhatTheRecordsShow(_Orchard):
    def _log(self, name, type_code="PE"):
        return ChemicalEvent.objects.create(
            history=self.history,
            type=type_code,
            date=timezone.make_aware(datetime(2026, 5, 4, 9, 0)),
            commercial_name=name,
        )

    def _row(self, name):
        return next(r for r in materials_list_rows(self.osp) if r["name"] == name)

    def test_a_row_with_no_reason_carries_the_records_kind_as_a_hint_not_an_answer(self):
        self.entry("Entrust SC", status="planned")
        self._log("Entrust SC")
        row = self._row("Entrust SC")
        self.assertEqual(row["reason"], "")
        self.assertEqual(row["reason_kind"], "Pest control")

    def test_the_operators_reason_stands_and_needs_no_hint(self):
        self.entry("Entrust SC", status="planned", reason_for_use="Codling moth")
        self._log("Entrust SC")
        row = self._row("Entrust SC")
        self.assertEqual(row["reason"], "Codling moth")
        self.assertEqual(row["reason_kind"], "")

    def test_a_logged_application_gives_its_date_for_the_in_use_offer(self):
        self.entry("Entrust SC", status="planned")
        self._log("Entrust SC")
        self.assertEqual(self._row("Entrust SC")["last_logged_on"], date(2026, 5, 4).isoformat())

    def test_the_latest_application_is_offered_not_the_first(self):
        # Review of back #473: the row's own record is its FIRST application.
        self.entry("Entrust SC", status="planned")
        for when in (datetime(2025, 5, 1, 9, 0), datetime(2026, 6, 2, 9, 0)):
            ChemicalEvent.objects.create(
                history=self.history, type="PE", date=timezone.make_aware(when), commercial_name="Entrust SC"
            )
        self.assertEqual(self._row("Entrust SC")["last_logged_on"], date(2026, 6, 2).isoformat())

    def test_a_row_the_records_never_name_has_no_date(self):
        self.entry("Cyd-X", status="planned")
        self.assertEqual(self._row("Cyd-X")["last_logged_on"], "")


class TheFormsOfferThePlansMaterials(_Orchard):
    URL = "/api/productions/plan-materials/?establishment_id={}"

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_the_plan_in_force_offers_its_materials_and_leaves_out_what_is_not_used(self):
        self.entry("Kocide 3000-O", manufacturer="Certis Biologicals", category="pest_disease_weed", status="in_use")
        self.entry("Old Fish Blend", status="discontinued")
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.URL.format(self.est.id))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["osp_id"], self.osp.pk)
        self.assertEqual(
            body["materials"],
            [
                {
                    "name": "Kocide 3000-O",
                    "manufacturer": "Certis Biologicals",
                    "category": "pest_disease_weed",
                    "status": "in_use",
                    "source": body["materials"][0]["source"],
                }
            ],
        )

    def test_another_company_cannot_read_it(self):
        stranger = User.objects.create_user(email="stranger@test.com", password="x")
        WorksIn.objects.create(
            user=stranger, company=Company.objects.create(name="Elsewhere LLC"), role=WorksIn.COMPANY_ADMIN
        )
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.get(self.URL.format(self.est.id)).status_code, 403)

    def test_no_plan_offers_nothing(self):
        self.osp.delete()
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(self.URL.format(self.est.id)).json()["materials"], [])


class AProductIsReadOnceByName(_Orchard):
    """Review of back #473: `plan_materials` returns a product twice where a catalog row must not fold into the
    operator's own (a lapsed OMRI listing, a prohibited substance); the twin carries no answers."""

    URL = TheFormsOfferThePlansMaterials.URL

    def _lapsed(self, **fields):
        product = OMRIProduct.objects.create(
            omri_id="snc-15985",
            product_name="SNS PC Insecticide Concentrate",
            manufacturer="Sierra Natural Science",
            delisted_on=date(2026, 9, 26),
        )
        self.osp.approved_omri_products.add(product)
        self.entry("SNS PC Insecticide Concentrate", omri_product=product, **fields)
        self.assertEqual(len([r for r in plan_materials(self.osp) if r.name == product.product_name]), 2)

    def _offered(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        return [m["name"] for m in client.get(self.URL.format(self.est.id)).json()["materials"]]

    def test_a_complete_entry_beside_its_lapsed_listing_is_not_listed_as_incomplete(self):
        self._lapsed(manufacturer="Sierra Natural Science", reason_for_use="Mites", status="in_use")
        self.assertEqual(incomplete_rows(self.osp), [])

    def test_a_product_marked_no_longer_used_is_not_offered_by_its_lapsed_listing(self):
        self._lapsed(status="discontinued")
        self.assertEqual(self._offered(), [])
        self.assertEqual(incomplete_rows(self.osp), [])

    def test_a_prohibited_substance_is_not_offered_under_the_operators_own_row(self):
        self.osp.approved_national_list_substances.add(NationalListSubstance.objects.get(substance_name="Strychnine"))
        self.entry("Strychnine", manufacturer="X", reason_for_use="Gophers", status="in_use")
        self.assertEqual(self._offered(), [])
