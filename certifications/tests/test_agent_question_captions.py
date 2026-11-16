"""The wizard names where the plan's own certifying agent asks each question (2026.10.26).

Questions are gated by the farm's answers, never by its agent: one answer fills WSDA's, CCOF's and
Oregon Tilth's forms. What follows the agent is the caption under the question ("WSDA asks this in
K Storage (AGR 2121), item 3a"), read from the same register as the packet's coverage page.

An agent with no register here gets no caption. Another agent's numbers would send the grower to a
form their agent never sent them.
"""

from django.test import SimpleTestCase, TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.services.agent_question_refs import refs_by_question
from certifications.services.certifier_register import certifiers, foreign_markers
from company.models import Company, Establishment
from users.models import User, WorksIn

WSDA = "Washington State Department of Agriculture"
CCOF = "CCOF Certification Services, LLC"
OTCO = "Oregon Tilth Certified Organic"


class ModuleDetailCaptionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Caption Orchards")
        self.user = User.objects.create_user(email="captions@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Caption Orchard", company=self.company, state="WA")
        self.client.force_authenticate(user=self.user)

    def detail(self, certifier, module="g6_2_storage"):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
        )
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp.id}/modules/{module}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_each_agent_is_shown_its_own_form_and_item(self):
        for certifier, agent, expected in (
            (WSDA, "WSDA", [{"form": "K Storage (AGR 2121)", "items": ["3a"]}]),
            (CCOF, "CCOF", [{"form": "G6.2 Storage (ORGB38)", "items": ["B2a"]}]),
            # C9 9.4-2's storage half cites the shared-storage answers since 2026-11-15.
            (
                OTCO,
                "OTCO",
                [
                    {"form": "C7 Crop Harvest, Processing, Storage, & Transport", "items": ["7.4-1a"]},
                    {"form": "C9 Contamination Prevention", "items": ["9.4-2"]},
                ],
            ),
        ):
            with self.subTest(agent):
                refs = self.detail(certifier)["agent_refs"]
                self.assertEqual(refs["agent"], agent)
                self.assertEqual(refs["refs"]["storage_shared_separation"], expected)

    def test_an_agent_without_a_register_or_no_agent_gets_no_caption(self):
        self.assertIsNone(self.detail("Organic Certifiers, Inc.")["agent_refs"])
        self.assertIsNone(self.detail("")["agent_refs"])

    def test_the_definition_is_the_same_for_every_agent(self):
        """Captions ride beside the definition, so the golden fixture stays agent-neutral."""
        self.assertEqual(self.detail(WSDA)["definition"], self.detail(CCOF)["definition"])

    def test_a_question_asked_on_two_forms_names_both(self):
        refs = self.detail(WSDA, module="g6_1_harvest_transport")["agent_refs"]["refs"]["who_harvests"]
        self.assertEqual(
            refs,
            [
                {"form": "I Farm Equipment (AGR 2121)", "items": ["3"]},
                {"form": "J Harvest (AGR 2121)", "items": ["1"]},
            ],
        )


class NoForeignIdentifierTests(SimpleTestCase):
    def test_no_caption_names_another_agents_form(self):
        for agent in certifiers():
            foreign = foreign_markers(agent)
            with self.subTest(agent):
                names = {ref["form"] for refs in refs_by_question(agent).values() for ref in refs}
                self.assertTrue(names)
                for name in names:
                    for marker in foreign:
                        self.assertNotIn(marker, name)

    def test_a_row_the_question_does_not_answer_is_not_named(self):
        """A not-covered row may cite a related question (CCOF G6.2 B7 cites `material_tier`), and an
        interpretation row is Trazo's note, not the agent's item. Naming either would tell the grower
        this answer fills an item it does not."""
        ccof = refs_by_question("ccof")["g9_0_facility_pest.material_tier"]
        self.assertNotIn("B7", [i for ref in ccof if ref["form"] == "G6.2 Storage (ORGB38)" for i in ref["items"]])
        wsda = refs_by_question("wsda").get("materials_application.materials_list_panel", ())
        self.assertNotIn("WSDA List cross-reference", [i for ref in wsda for i in ref["items"]])
