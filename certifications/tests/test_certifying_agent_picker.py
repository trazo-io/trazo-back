"""The certifier picker: one list of agents, one resolver, and the plan's own answer.

🔴 2026-09-10 — the certifying agent was free text in two places, matched against an alias table
that knew three agents, and a first-year applicant had nowhere to name one. 62% of the October
send list is certified by an agent the table did not know, so their packets were numbered to
CCOF's forms with nothing on screen saying so. See `certifications/certifying_agents.py`.

What is pinned here:

  * the picker and the resolver are one list, and every register folder is on it;
  * no spelling means two agents, and ambiguous abbreviations mean none;
  * the plan's own answer is read first, and an unknown answer never borrows another record's;
  * the API offers the list with the same "own numbering" promise the packet keeps.
"""

from django.test import SimpleTestCase, TestCase

from rest_framework.test import APIClient

from certifications.certifying_agents import AGENTS, agent_for_name, normalize_agent_name
from certifications.models import Certification, OrganicSystemPlan
from certifications.services.certifier_register import certifiers
from certifications.services.packet_coverage import PacketAgent, packet_agent, packet_certifier
from company.models import Company, Establishment
from users.models import User, WorksIn


def _spellings(agent):
    return [s for s in (agent.name, agent.short_name, *agent.aliases) if s]


class AgentListTests(SimpleTestCase):
    def test_every_registered_certifier_is_offered_by_the_picker(self):
        """A register folder with no picker entry is an agent whose numbering nobody can select."""
        slugs = {agent.slug for agent in AGENTS}
        self.assertTrue(certifiers(), "the register could not be read, so this test proves nothing")
        for folder in certifiers():
            self.assertIn(folder, slugs, f"register folder {folder!r} has no entry in certifying_agents")

    def test_slugs_and_names_are_unique(self):
        self.assertEqual(len({a.slug for a in AGENTS}), len(AGENTS))
        self.assertEqual(len({normalize_agent_name(a.name) for a in AGENTS}), len(AGENTS))

    def test_every_spelling_resolves_to_its_own_agent(self):
        for agent in AGENTS:
            for spelling in _spellings(agent):
                self.assertEqual(agent_for_name(spelling), agent, spelling)

    def test_no_spelling_is_claimed_by_two_agents(self):
        owner = {}
        for agent in AGENTS:
            for spelling in _spellings(agent):
                key = normalize_agent_name(spelling)
                self.assertEqual(owner.setdefault(key, agent.slug), agent.slug, f"{spelling!r} means two agents")

    def test_ambiguous_abbreviations_mean_no_agent(self):
        # ODA: Oregon or Oklahoma. CDA: Colorado (and not California, whose agency is CDFA and
        # certifies no one). MDA: Maryland, Minnesota, Montana. KDA: Kentucky or Kansas.
        for abbreviation in ("ODA", "CDA", "MDA", "KDA", "CDFA"):
            self.assertIsNone(agent_for_name(abbreviation), abbreviation)

    def test_matching_is_exact_after_normalisation_never_fuzzy(self):
        self.assertEqual(agent_for_name("  oregon tilth.  ").slug, "otco")
        self.assertEqual(agent_for_name("Natures International Certification Services").slug, "nics")
        self.assertEqual(agent_for_name("organic certifiers inc").slug, "oci")
        self.assertIsNone(agent_for_name("Oregon Tilt"))
        self.assertIsNone(agent_for_name("Organic Certifier"))
        self.assertIsNone(agent_for_name(""))
        self.assertIsNone(agent_for_name(None))


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Bench Block Orchards LLC")
        self.user = User.objects.create_user(email="picker@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Bench Block", company=self.company, state="WA")

    def _plan(self, stated="", version=1, status="draft"):
        return OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=version, status=status, certifier_name=stated
        )

    def _certificate(self, agent):
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="WA-ORG-2011-0447",
            certifier_name=agent,
        )


class ThePlansAnswerTests(_Farm):
    def test_a_first_year_plan_names_its_agent_with_no_certificate(self):
        osp = self._plan("Oregon Tilth Certified Organic")
        self.assertEqual(packet_agent(osp), PacketAgent("Oregon Tilth Certified Organic", "otco", "plan"))
        self.assertEqual(packet_certifier(osp), ("otco", True))

    def test_the_plans_answer_wins_over_the_certificate_of_record(self):
        """An operation moving from WSDA to Oregon Tilth holds a WSDA certificate and files this plan
        with Oregon Tilth. The plan is the one that says who reads the packet."""
        self._certificate("Washington State Department of Agriculture")
        osp = self._plan("Oregon Tilth Certified Organic")
        self.assertEqual(packet_certifier(osp), ("otco", True))

    def test_a_blank_answer_falls_through_to_the_certificate(self):
        self._certificate("Washington State Department of Agriculture")
        osp = self._plan("")
        agent = packet_agent(osp)
        self.assertEqual((agent.slug, agent.source), ("wsda", "certificate"))

    def test_an_unknown_answer_never_borrows_the_certificates_agent(self):
        """⛔ The operator named who reviews this plan. Numbering it to the certificate's agent
        instead would be a packet for a reviewer the operator did not name."""
        self._certificate("Washington State Department of Agriculture")
        osp = self._plan("Cascade Organic Certifiers")
        agent = packet_agent(osp)
        self.assertEqual((agent.name, agent.slug, agent.source), ("Cascade Organic Certifiers", None, "plan"))
        self.assertEqual(packet_certifier(osp), ("ccof", False))

    def test_nothing_named_anywhere_is_an_empty_answer(self):
        self.assertEqual(packet_agent(self._plan()), PacketAgent())


class PickerAPITests(_Farm):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _osps(self, osp_id=None, suffix=""):
        base = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/"
        return f"{base}{osp_id}/{suffix}" if osp_id else base

    def test_the_list_says_which_agents_the_packet_numbers_to_their_own_forms(self):
        response = self.client.get("/api/certifications/certifying-agents/")
        self.assertEqual(response.status_code, 200)
        by_slug = {row["slug"]: row for row in response.data}
        self.assertEqual(len(by_slug), len(AGENTS))
        for folder in certifiers():
            self.assertTrue(by_slug[folder]["own_numbering"], folder)
        self.assertFalse(by_slug["oci"]["own_numbering"])
        self.assertEqual(by_slug["oci"]["name"], "Organic Certifiers, Inc.")
        names = [normalize_agent_name(row["name"]) for row in response.data]
        self.assertEqual(names, sorted(names))

    def test_the_list_needs_a_login(self):
        self.assertIn(APIClient().get("/api/certifications/certifying-agents/").status_code, (401, 403))

    def test_a_plan_is_started_with_its_agent(self):
        response = self.client.post(self._osps(), {"certifier_name": "  Organic Certifiers, Inc. "}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            OrganicSystemPlan.objects.get(pk=response.data["id"]).certifier_name, "Organic Certifiers, Inc."
        )
        self.assertEqual(
            response.data["packet_agent"],
            {"name": "Organic Certifiers, Inc.", "slug": "oci", "source": "plan", "own_numbering": False},
        )

    def test_the_plan_list_carries_the_agent_the_plan_page_shows(self):
        self._certificate("WSDA")
        self._plan()
        row = self.client.get(self._osps()).data
        row = (row["results"] if isinstance(row, dict) else row)[0]
        self.assertEqual(row["certifier_name"], "")
        self.assertEqual(
            row["packet_agent"], {"name": "WSDA", "slug": "wsda", "source": "certificate", "own_numbering": True}
        )

    def test_a_draft_takes_the_answer_and_the_next_version_keeps_it(self):
        osp = self._plan()
        response = self.client.patch(
            self._osps(osp.id), {"certifier_name": "Oregon Tilth Certified Organic"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        osp.refresh_from_db()
        self.assertEqual(osp.certifier_name, "Oregon Tilth Certified Organic")

        OrganicSystemPlan.objects.filter(pk=osp.pk).update(status="active")
        clone = self.client.post(self._osps(osp.id, "new-version/"))
        self.assertIn(clone.status_code, (200, 201), clone.data)
        self.assertEqual(
            OrganicSystemPlan.objects.get(pk=clone.data["id"]).certifier_name, "Oregon Tilth Certified Organic"
        )

    def test_a_submitted_plan_refuses_a_new_answer(self):
        """The agent is part of what was filed; changing it after submission rewrites the record."""
        osp = self._plan("WSDA", status="submitted")
        response = self.client.patch(self._osps(osp.id), {"certifier_name": "Oregon Tilth"}, format="json")
        self.assertGreaterEqual(response.status_code, 400)
        osp.refresh_from_db()
        self.assertEqual(osp.certifier_name, "WSDA")
