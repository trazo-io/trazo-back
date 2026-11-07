"""Pest control materials in handling and storage facilities: CCOF Materials Application §F and §G.

§F lists facility pest control "by National List material type ... each with Used?, Where Used, and Applied by
fumigation/fogging?"; §G "any pest control material used in a post-harvest handling or crop-storage facility that
does not fit a §F National List type". § 205.271(d) allows such a material only when the handler and the
certifying agent agree on the substance, the method and contact prevention.
"""

import io
from datetime import date

from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.services.facility_pest import section_f, tier_review_lines
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from users.models import User, WorksIn

AT = "2026-11-07T12:00:00Z"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def setUp(self):
        self.est = Establishment.objects.create(name="Bin Farm", company=Company.objects.create(name="Bin LLC"))
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def entry(self, name, **kw):
        return PlanMaterialEntry.objects.create(osp=self.osp, product_name=name, category="facility_pest", **kw)

    def g9(self, tier):
        self.osp.module_responses = {
            "schema_version": 1,
            "parcel_modules": {},
            "modules": {"g9_0_facility_pest": {"answers": {"material_tier": {"at": AT, "value": tier}}}},
        }
        self.osp.save(update_fields=["module_responses"])


class SectionF(_Plan):
    def test_every_type_prints_in_ccofs_order_with_its_columns(self):
        self.entry(
            "Terro ant bait",
            facility_material_type="boric_acid",
            where_used="Packing shed",
            applied_by_fumigation=False,
        )
        self.entry("Trécé pheromone lure", facility_material_type="pheromones", where_used="Dry storage")
        rows = {r.label: r for r in section_f(list(self.osp.plan_material_entries.all()))}
        self.assertEqual(len(rows), 11)
        self.assertTrue(rows["Boric acid"].used)
        self.assertEqual(rows["Boric acid"].where_used, ("Packing shed",))
        self.assertEqual(rows["Boric acid"].fumigation, "No")
        self.assertEqual(rows["Pheromones"].fumigation, "not stated")
        self.assertFalse(rows["Vitamin D3"].used)

    def test_the_materials_pdf_prints_the_table(self):
        self.entry(
            "Terro ant bait",
            facility_material_type="boric_acid",
            where_used="Packing shed",
            applied_by_fumigation=False,
        )
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("Pest control in handling and storage facilities, by National List type", page)
        self.assertIn("Terro ant bait", page)
        self.assertIn("Packing shed", page)
        self.assertIn("Vitamin D3", page)

    def test_nothing_prints_without_facility_rows(self):
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        self.assertNotIn("by National List type", page)


class SectionG(_Plan):
    def test_a_material_outside_the_types_without_an_agreement_is_flagged(self):
        self.entry(
            "MAX Fog Roach Killer",
            facility_material_type="not_national_list",
            where_used="Storage room",
            applied_by_fumigation=True,
        )
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("MAX Fog Roach Killer; used in Storage room; applied by fumigation or fogging", page)
        self.assertIn("[REVIEW] MAX Fog Roach Killer is not a National List type and no agreement", page)
        self.assertIn("§ 205.271(d)", page)

    def test_a_recorded_agreement_prints_and_clears_the_review(self):
        self.entry(
            "MAX Fog Roach Killer",
            facility_material_type="not_national_list",
            where_used="Storage room",
            applied_by_fumigation=True,
            agent_review=PlanMaterialEntry.REVIEW_APPROVED,
            agent_review_reference="Letter 2026-14",
            agent_review_date=date(2026, 3, 1),
        )
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("approved materials list", page)
        self.assertNotIn("no agreement with the certifying agent is recorded", page)

    def test_a_row_without_its_type_is_flagged(self):
        self.entry("Mystery spray")
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("[REVIEW] Mystery spray is filed as facility pest control without its National List type", page)


class G9Tier(_Plan):
    def test_materials_said_to_be_used_with_none_on_the_list(self):
        self.assertIn("holds none", tier_review_lines("national_list", [])[0])

    def test_none_said_with_rows_on_the_list(self):
        e = self.entry("Sticky trap", facility_material_type="sticky_traps")
        self.assertIn("Sticky trap", tier_review_lines("none", [e])[0])

    def test_national_list_only_with_a_material_outside_it(self):
        e = self.entry("Fogger", facility_material_type="not_national_list")
        self.assertTrue(
            any("not a National List type: Fogger" in line for line in tier_review_lines("national_list", [e]))
        )

    def test_the_review_prints_beside_the_g9_answer(self):
        self.g9("national_list")
        page = _text(generate_module_pdf(self.osp, "g9_0_facility_pest"))
        self.assertIn("[REVIEW] The plan says pest control materials are used in its structures", page)

    def test_a_consistent_answer_prints_no_review(self):
        self.entry("Sticky trap", facility_material_type="sticky_traps")
        self.g9("national_list")
        self.assertNotIn("[REVIEW] The plan says", _text(generate_module_pdf(self.osp, "g9_0_facility_pest")))


class Api(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="fpest@test.com", password="x", is_verified=True)
        company = Company.objects.create(name="Pest Co")
        WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Pest Ranch", company=company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=est, version_number=1, status="draft", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)
        base = f"/api/companies/{company.pk}/establishments/{est.pk}/osps/{self.osp.pk}"
        self.answer_url = f"{base}/materials-list/answer/"
        self.list_url = f"{base}/materials-list/"

    def test_a_facility_row_records_its_three_columns(self):
        resp = self.client.post(
            self.answer_url,
            {
                "name": "Terro ant bait",
                "category": "facility_pest",
                "facility_material_type": "boric_acid",
                "where_used": "Packing shed",
                "applied_by_fumigation": False,
            },
            format="json",
        )
        self.assertIn(resp.status_code, (200, 201), resp.content)
        row = next(r for r in self.client.get(self.list_url).data["materials"] if r["name"] == "Terro ant bait")
        self.assertEqual(row["facility_material_type"], "boric_acid")
        self.assertEqual(row["where_used"], "Packing shed")
        self.assertIs(row["applied_by_fumigation"], False)

    def test_the_columns_are_refused_on_another_category(self):
        resp = self.client.post(
            self.answer_url,
            {"name": "Copper", "category": "pest_disease_weed", "where_used": "Orchard"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("where_used", resp.data)
