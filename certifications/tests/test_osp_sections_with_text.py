"""
`sections_with_text`: one count of § 205.201(a) narratives with text, for every surface.

Before 2026-10-17 the onboarding checklist ticked "The Organic System Plan in Trazo has text in all
six sections" from `section_completion`, which counts any non-blank narrative. One character in
each section ticked it while the OSP page read "0 of 6 narrative sections have text" and submit
refused the plan. The checklist now reads `sections_with_text`, which applies the submit gate's
rule (material floor, padding) plus the audit PDF's (a)(2) hold for unreferenced registry entries.
"""

from unittest import mock

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
from certifications.services import osp_sections
from certifications.services.osp_sections import sections_missing_text, sections_with_text
from company.models import Company, Establishment
from users.models import User, WorksIn

# Clears both submit-gate bars: at least 400 characters and not padding.
MATERIAL = (
    "Sixty acres of certified organic tree crops on three blocks: Hass avocado, "
    "Valencia orange, and Nonpareil almond. Fertility comes from composted green "
    "waste banded under the canopy each autumn plus fish emulsion through the drip "
    "at bloom. Winter cover crops of triticale and crimson clover are drilled into "
    "the row middles in October and mowed flat in March. Pest pressure is scouted "
    "weekly against UC IPM thresholds before any material is applied, and a "
    "thirty-foot mowed buffer separates us from the conventional lemon block."
)
NO_WARNING = {"has_warning": False, "entries_not_in_narrative": []}


def _sections(**narratives):
    return {k: {"narrative": narratives.get(k, ""), "last_updated": None} for k in OSP_SECTION_KEYS}


class SectionsWithTextTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Count Farm")
        self.est = Establishment.objects.create(name="E", company=self.company)

    def _osp(self, sections):
        n = OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1
        return OrganicSystemPlan.objects.create(establishment=self.est, version_number=n, sections=sections)

    def test_one_character_per_section_is_not_text(self):
        osp = self._osp(_sections(**{k: "x" for k in OSP_SECTION_KEYS}))
        self.assertEqual(osp.section_completion, 1.0, "the loose count the checklist used to read")
        self.assertEqual(sections_with_text(osp, diff=NO_WARNING), 0)

    def test_padding_is_not_text(self):
        osp = self._osp(_sections(practices_procedures="Test " * 120, commingling_barriers=MATERIAL))
        self.assertEqual(sections_with_text(osp, diff=NO_WARNING), 1)

    def test_six_material_narratives_count_six(self):
        osp = self._osp(_sections(**{k: MATERIAL for k in OSP_SECTION_KEYS}))
        self.assertEqual(sections_with_text(osp, diff=NO_WARNING), 6)

    def test_an_unreferenced_registry_entry_holds_back_inputs_list(self):
        # The audit PDF's rule: (a)(2) does not count while a registered input is missing from it.
        osp = self._osp(_sections(**{k: MATERIAL for k in OSP_SECTION_KEYS}))
        diff = {"has_warning": True, "entries_not_in_narrative": [{"source": "omri", "name": "Entrust"}]}
        self.assertEqual(sections_with_text(osp, diff=diff), 5)

    def test_a_thin_registry_is_a_banner_not_a_hold(self):
        # has_warning also fires for a thin registry. The PDF still counts (a)(2) then, and so
        # does submit, so this count must too (review of back #172).
        osp = self._osp(_sections(**{k: MATERIAL for k in OSP_SECTION_KEYS}))
        thin = {"has_warning": True, "entries_not_in_narrative": []}
        self.assertEqual(sections_with_text(osp, diff=thin), 6)

    def test_registry_is_read_when_no_diff_is_passed(self):
        # An empty registry under a material (a)(2) narrative: thin, nothing unreferenced.
        osp = self._osp(_sections(**{k: MATERIAL for k in OSP_SECTION_KEYS}))
        self.assertTrue(osp_sections.registry_sync_diff(osp)["has_warning"])
        self.assertEqual(sections_with_text(osp), 6)

    def test_submit_gate_reads_the_same_rule(self):
        osp = self._osp(_sections(practices_procedures=MATERIAL, inputs_list="brief"))
        from certifications.views import OrganicSystemPlanViewSet

        self.assertEqual(OrganicSystemPlanViewSet()._missing_osp_sections(osp), sections_missing_text(osp))
        self.assertEqual(len(sections_missing_text(osp)), 5)


class SectionsWithTextApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="count@test.com", password="x")
        self.company = Company.objects.create(name="Count Farm")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="E", company=self.company)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            sections=_sections(practices_procedures=MATERIAL, recordkeeping_description=MATERIAL, inputs_list="x"),
        )
        self.base = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/"

    def test_list_payload_carries_the_count(self):
        res = self.client.get(self.base)
        self.assertEqual(res.status_code, 200)
        rows = res.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertEqual(rows[0]["sections_with_text"], 2)
        self.assertAlmostEqual(rows[0]["section_completion"], 3 / 6, msg="unchanged for its other readers")

    def test_detail_payload_carries_the_count_and_reads_the_registry_once(self):
        with mock.patch("certifications.serializers.registry_sync_diff", wraps=osp_sections.registry_sync_diff) as spy:
            res = self.client.get(f"{self.base}{self.osp.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["sections_with_text"], 2)
        self.assertEqual(spy.call_count, 1)
