"""A blank question the plan's own agent asks is flagged, never blocking (2026.11.04).

Trazo marks a question optional when the plan reads true without it. The agent's form can still ask
it: WSDA's B Transplants item 1a asks what seedlings are grown, and the seedlings description is
optional here. Left blank, the module PDF printed "Not answered (optional)" and the wizard said
nothing, so the grower learned the agent wanted it only when the agent wrote back.

Flagged: showing, blank, not required by Trazo (those already block completion), and cited by a row
of the agent's own register that applies to this plan and that the form does not print as optional.
Not flagged: a question the plan reads blank as No (a "none used" tick), an agent with no register
here, and anything in a module attested not applicable. Completion never waits on any of it.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.agent_question_refs import agent_asks
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from users.models import User, WorksIn

WSDA = "Washington State Department of Agriculture"
CCOF = "CCOF Certification Services, LLC"
OCI = "Organic Certifiers, Inc."
AT = "2026-11-02T10:00:00+00:00"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Blank Flag Orchards")
        self.user = User.objects.create_user(email="blank-flags@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Blank Flag Orchard", company=self.company, state="WA")
        self.client.force_authenticate(user=self.user)

    def plan(self, certifier, modules=None):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules or {}},
        )

    def url(self, osp, tail="modules/"):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp.id}/{tail}"

    def rows(self, osp):
        response = self.client.get(self.url(osp))
        self.assertEqual(response.status_code, 200)
        return response.data["agent"], {row["key"]: row["agent_asks_blank"] for row in response.data["modules"]}


class ModuleListFlagsTests(_Plan):
    def test_a_blank_question_wsda_asks_is_listed_for_its_module(self):
        agent, rows = self.rows(self.plan(WSDA))
        self.assertEqual(agent, "WSDA")
        self.assertIn("seedlings_description", rows["g3_1_seedlings"])

    def test_an_answered_one_is_not(self):
        osp = self.plan(
            WSDA,
            {"g3_1_seedlings": {"answers": {"seedlings_description": {"at": AT, "value": "Tomato starts, 2 trays"}}}},
        )
        self.assertNotIn("seedlings_description", self.rows(osp)[1]["g3_1_seedlings"])

    def test_no_question_trazo_requires_is_listed(self):
        """Required ones already block completion; flagged twice they read as two problems."""
        _agent, rows = self.rows(self.plan(WSDA))
        self.assertTrue(any(rows.values()))
        for module_key, keys in rows.items():
            questions = {q.key: q for p in MODULES_BY_KEY[module_key].pages for q in p.questions}
            for key in keys:
                with self.subTest(f"{module_key}.{key}"):
                    self.assertFalse(questions[key].required)
                    self.assertNotIn(questions[key].kind, ("info", "upload"))

    def test_a_none_used_tick_left_blank_is_not_flagged(self):
        """CCOF's materials preamble cites `no_materials_used`; the plan reads its blank as No and shows
        the materials list, so a grower who listed materials would be nagged for not ticking it."""
        rows = self.rows(self.plan(CCOF))[1]["materials_application"]
        for key in ("no_materials_used", "fertilizers_none_used", "post_harvest_contact_none_used"):
            self.assertNotIn(key, rows)

    def test_a_question_cited_only_on_a_row_the_form_prints_optional_is_not_flagged(self):
        wsda = [form for form in load_forms("wsda") if form.served]
        required_refs = {
            k for f in wsda for i in f.items if i.kind == "question" and not i.optional for k in i.questions
        }
        optional_only = {
            k for f in wsda for i in f.items if i.kind == "question" and i.optional for k in i.questions
        } - required_refs
        self.assertIn("g3_0_seeds.seeds_additional_notes", optional_only)
        rows = self.rows(self.plan(WSDA))[1]
        for cited in optional_only:
            module_key, _, key = cited.partition(".")
            self.assertNotIn(key, rows.get(module_key, []), cited)

    def test_an_agent_without_a_register_or_no_agent_gets_no_flags(self):
        for certifier in (OCI, ""):
            with self.subTest(certifier or "no agent"):
                agent, rows = self.rows(self.plan(certifier))
                self.assertIsNone(agent)
                self.assertEqual({key for key, keys in rows.items() if keys}, set())

    def test_a_module_attested_not_applicable_has_no_flags(self):
        osp = self.plan(
            WSDA,
            {
                "g3_1_seedlings": {
                    "status": "not_applicable",
                    "not_applicable": True,
                    "na_attestation": {"by": self.user.pk, "at": AT},
                    "answers": {},
                }
            },
        )
        self.assertEqual(self.rows(osp)[1]["g3_1_seedlings"], [])


class WizardAndCompletionTests(_Plan):
    def test_the_module_detail_names_the_asked_questions_beside_the_captions(self):
        response = self.client.get(self.url(self.plan(WSDA), "modules/g3_1_seedlings/"))
        refs = response.data["agent_refs"]
        self.assertIn("seedlings_description", refs["asked"])
        self.assertTrue(set(refs["asked"]) <= set(refs["refs"]))

    def test_completion_does_not_wait_on_a_flagged_question(self):
        osp = self.plan(WSDA)
        flagged = self.rows(osp)[1]["g3_1_seedlings"]
        self.assertIn("seedlings_description", flagged)
        response = self.client.put(self.url(osp, "modules/g3_1_seedlings/"), {"complete": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        osp.refresh_from_db()
        self.assertTrue(osp.module_responses["modules"]["g3_1_seedlings"].get("completed_at"))

    def test_an_answered_question_leaves_the_server_list(self):
        osp = self.plan(WSDA)
        self.client.put(
            self.url(osp, "modules/g3_1_seedlings/"),
            {"answers": {"seedlings_description": "Pepper starts"}},
            format="json",
        )
        self.assertNotIn("seedlings_description", self.rows(osp)[1]["g3_1_seedlings"])

    def test_agent_asks_returns_none_for_an_unregistered_agent(self):
        self.assertIsNone(agent_asks(self.plan(OCI)))


class ModulePdfTests(_Plan):
    def test_the_pdf_names_the_agent_and_item_instead_of_optional(self):
        text = _text(generate_module_pdf(self.plan(WSDA), "g3_1_seedlings"))
        self.assertIn("Not yet answered. WSDA asks this in B Transplants (AGR 2121), item 1a.", text)

    def test_an_agent_without_a_register_still_reads_optional(self):
        text = _text(generate_module_pdf(self.plan(OCI), "g3_1_seedlings"))
        self.assertNotIn("asks this in", text)
        self.assertIn("Not answered (optional).", text)
