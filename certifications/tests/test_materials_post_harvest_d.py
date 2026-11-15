"""CCOF Materials Application §D, read end to end (2026-11-09).

§D: "If you conduct post-harvest handling: list materials that directly contact organic crops during
handling, such as: wash water additives, sanitizers, gases, etc." with Brand Name, Manufacturer and Reason for
use, or "Not applicable". The register held §D partial on three claims, each checked against the code:

- "§ 205.605 has zero seeded rows": migration 0038 seeds § 205.605(b) (`test_national_list_205_605`).
- "'SaniDate 5.0' on the log and 'Peracetic acid' on the plan still read as two products": the operator's
  identity decision ties a logged sanitizer name to a plan row, and the §D statement then stands. Proved here.
- "the pilot's sanitizer record cites the wrong section": the dossier prints the operator's own reference
  under "Post-Harvest Sanitation (7 CFR 205.272 + § 205.605)".

Gases have no record of their own; the list is their only source, as for growing media.
"""

import io

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import MaterialIdentityDecision as MID
from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.services.material_identity import record_decision
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import unmatched_logged_materials
from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from product.models import Parcel
from users.models import User, WorksIn


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class SectionDTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Wash Line Orchards")
        self.user = User.objects.create_user(email="wash@test.com", password="x", is_verified=True)
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Wash Line", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="Packing Block", establishment=self.est, area=2.0)
        self.history = Production.objects.create(name="Pears 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.wash = ProductionEvent.objects.create(
            history=self.history, date=timezone.now(), description="flume", type="PH", sanitizer_name="SaniDate 5.0"
        )
        self.row = PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Peracetic acid wash-water sanitizer",
            manufacturer="BioSafe Systems",
            reason_for_use="Wash water sanitizer",
            category="post_harvest",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def put(self, answers):
        url = (
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}"
            "/modules/materials_application/"
        )
        return self.client.put(url, {"answers": answers}, format="json")

    def decide(self):
        return record_decision(
            self.osp,
            self.user,
            {
                "source": "sanitizer",
                "logged_name": "SaniDate 5.0",
                "decision": MID.SAME_AS,
                "target_kind": MID.TARGET_PLAN_ENTRY,
                "target_id": self.row.pk,
                "event_ids": [self.wash.pk],
                "formulation_difference_acknowledged": True,
                "formulation_note": "SaniDate 5.0 is the brand of the peracetic acid sanitizer on the list.",
            },
        )

    def test_the_listed_statement_waits_for_the_operators_identity_decision(self):
        self.assertIn("SaniDate 5.0", unmatched_logged_materials(self.osp))
        refused = self.put({"post_harvest_contact_listed": True})
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertIn("SaniDate 5.0", str(refused.json()["answers"]["post_harvest_contact_listed"]))

        self.decide()
        self.assertNotIn("SaniDate 5.0", unmatched_logged_materials(self.osp))
        accepted = self.put({"post_harvest_contact_listed": True})
        self.assertEqual(accepted.status_code, 200, accepted.content)

    def test_the_section_d_table_prints_brand_manufacturer_and_reason_with_a_gas_row(self):
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Carbon dioxide (controlled atmosphere)",
            manufacturer="Airgas",
            reason_for_use="Controlled-atmosphere storage",
            category="post_harvest",
        )
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        block = page[page.index("Post-harvest contact materials") :]
        for words in (
            "Peracetic acid wash-water sanitizer",
            "BioSafe Systems",
            "Wash water sanitizer",
            "Carbon dioxide (controlled atmosphere)",
            "Airgas",
        ):
            self.assertIn(words, block)


class RegisterRowsTests(TestCase):
    def test_d_is_covered(self):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms("ccof") if "ORGB41" in (f.code, f.document_id))
        self.assertEqual(next(i for i in form.items if i.ref == "D").status, "covered")
