"""Storage detail (content 2026.12.02).

OTCO C7 7.7-1 and CCOF G6.2 A1 ask whether the operation still owns the crop while it sits in someone else's storage;
OTCO 7.2-2 and CCOF G6.4 A3 accept a flow chart or a written description; OTCO 7.1-1 and 7.1-2 ask activities and
crops per on-farm facility, which the operation's own facility records have stated since 2026-11-07.
"""

import io

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

G62 = MODULES_BY_KEY["g6_2_storage"]
G64 = MODULES_BY_KEY["g6_4_handling"]
AT = "2026-11-10T10:00:00Z"


def _question(module, key):
    return next(q for p in module.pages for q in p.questions if q.key == key)


class OwnershipTests(SimpleTestCase):
    def test_it_is_asked_only_for_storage_somewhere_else(self):
        shown = lambda answers: {q.key for _p, q in visible_questions(G62, answers)}  # noqa: E731
        self.assertNotIn("owns_crop_in_storage", shown({"storage_locations": ["on_farm_cold"]}))
        for off_farm in ("commercial_cold_off_farm", "certified_handler", "uncertified_facility"):
            self.assertIn("owns_crop_in_storage", shown({"storage_locations": [off_farm]}))


class FlowChartTests(SimpleTestCase):
    def test_both_questions_say_either_one_answers(self):
        self.assertIn("either one answers the request", _question(G64, "process_flow").coaching["en"])
        self.assertIn("each answer the request", _question(G64, "facility_docs").coaching["en"])


class PerFacilityTests(TestCase):
    def test_an_own_facility_prints_its_role_and_products(self):
        est = Establishment.objects.create(name="Home Farm", company=Company.objects.create(name="Home"))
        PostHarvestFacility.objects.create(
            establishment=est,
            name="Wash Shed",
            facility_type="packer",
            role="both",
            operated_by="this_operation",
            products_detail="Fresh blueberries, 1 pint clamshells",
        )
        osp = OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "g6_2_storage": {
                        "answers": {"storage_locations": {"at": AT, "value": ["on_farm_cold"]}},
                    }
                },
            },
        )
        page = " ".join(extract_text(io.BytesIO(generate_module_pdf(osp, "g6_2_storage"))).split())
        self.assertIn("Wash Shed", page)
        self.assertIn("Stores and handles the crop", page)
        self.assertIn("Fresh blueberries, 1 pint clamshells", page)


class RegisterRowsTests(SimpleTestCase):
    def test_the_rows_are_covered(self):
        for agent, code, refs in (
            ("otco", "C7", ("7.1-1", "7.1-2", "7.2-2", "7.6-2", "7.7-1")),
            ("ccof", "G6.2", ("A1",)),
            ("ccof", "G6.4", ("A3",)),
        ):
            form = next(f for f in load_forms(agent) if code in (f.code, f.document_id))
            for ref in refs:
                self.assertEqual(next(i for i in form.items if i.ref == ref).status, "covered", (agent, ref))
