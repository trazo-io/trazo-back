"""An annual update cannot be signed or filed saying a plan section is unchanged when it changed.

WHY THIS EXISTS
---------------
Overall review 2026-11, OV-PK-O01. The § 205.406(a) annual update lets the grower attest each
§ 205.201(a) section unchanged since the prior plan, all six in one click with "Mark all
unchanged". Nothing compared the two plan versions when the update was signed, although the
comparison existed: the same packet's 02s then printed "answers in them differ between plan v1 and
v3" under the filing that said they had not. A certifier reading 02 and then 02s asks which is
true.

Signing is now refused while an attested section differs between the plan the update
continues and the version it produced, naming each section and what differs in it. "Differs" is
`plan_version_changes.section_differences`, the comparison 02s prints: answers compiled into the
section, the materials list, the operator's own narrative and the record types confirmed. Saving
a draft is never refused, and an update with no second version to compare (a first year in
Trazo, a plan continued as it is) is the operator's statement alone.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate, PlanMaterialEntry
from certifications.services.annual_update_filing import ATTESTED_UNCHANGED_BUT_DIFFERS
from certifications.services.osp_fork import fork_plan
from company.models import Company, Establishment
from users.models import User, WorksIn


def _answer(osp, module_key, question, value):
    osp = OrganicSystemPlan.objects.get(pk=osp.pk)
    responses = osp.module_responses or {"schema_version": 1, "modules": {}, "parcel_modules": {}}
    module = responses.setdefault("modules", {}).setdefault(module_key, {"status": "in_progress", "answers": {}})
    module.setdefault("answers", {})[question] = {"value": value, "at": "2026-01-05T10:00:00Z"}
    osp.module_responses = responses
    osp.save(update_fields=["module_responses"])


def _narrative(osp, key, text):
    osp = OrganicSystemPlan.objects.get(pk=osp.pk)
    sections = dict(osp.sections or {})
    sections[key] = {**(sections.get(key) or {}), "narrative_manual": text}
    osp.sections = sections
    osp.save(update_fields=["sections"])


ALL_SIX = {
    "practices_procedures": True,
    "inputs_list": True,
    "monitoring_plan": True,
    "recordkeeping_description": True,
    "commingling_barriers": True,
    "additional_certifier_info": True,
}


class _Renewal(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="attest@test.com", password="x", is_verified=True, first_name="Rosa", last_name="Lind"
        )
        self.company = Company.objects.create(name="Attest Orchards LLC")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Attest Orchard", company=self.company)
        self.v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        _answer(self.v1, "g6_0_production", "split_operation", False)
        self.client.force_authenticate(user=self.user)

    def _base(self):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osp-annual-updates/"

    def _fork(self):
        return fork_plan(OrganicSystemPlan.objects.get(pk=self.v1.pk), self.user)

    def _create(self, attestation):
        res = self.client.post(
            self._base(),
            {
                "prior_osp": self.v1.pk,
                "reporting_year": 2027,
                "changes_summary": "Started a conventional block next to the pears.",
                "sections_unchanged_attestation": attestation,
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])
        return OSPAnnualUpdate.objects.get(pk=res.json()["id"])

    def _sign(self, filing):
        return self.client.post(f"{self._base()}{filing.pk}/sign/", {"signer_title": "Owner"}, format="json")

    def _file(self, filing):
        return self.client.post(
            f"{self._base()}{filing.pk}/file/", {"filing_method": "email", "submitted_at": "2026-11-02"}, format="json"
        )


class RefusedTests(_Renewal):
    def test_signing_is_refused_when_a_section_attested_unchanged_differs(self):
        v2 = self._fork()
        _answer(v2, "g6_0_production", "split_operation", True)
        filing = self._create({"commingling_barriers": True, "practices_procedures": True})
        self.assertEqual(filing.new_osp_id, v2.pk, "the update must name the draft it produces")

        res = self._sign(filing)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:600])
        body = res.json()
        self.assertEqual(body["code"], ATTESTED_UNCHANGED_BUT_DIFFERS)
        self.assertEqual(body["action"], "sign")
        self.assertEqual((body["prior_osp_version"], body["new_osp_version"]), (1, 2))
        # split_operation compiles into (a)(5) only: practices is attested too and is not named.
        self.assertEqual([row["section"] for row in body["sections"]], ["commingling_barriers"])
        row = body["sections"][0]
        self.assertEqual((row["clause"], row["differs"]), ("(a)(5)", ["answers"]))
        self.assertEqual([m["code"] for m in row["modules"]], ["G6.0"])
        self.assertIn("Not signed.", body["detail"])
        self.assertIn("§ 205.201(a)(5)", body["detail"])
        self.assertNotIn("(a)(1)", body["detail"])
        filing.refresh_from_db()
        self.assertIsNone(filing.signed_at)
        self.assertEqual(filing.signed_content_sha256, "")

    def test_no_request_field_skips_the_comparison(self):
        """`compare_plan_versions=False` exists for the specimen seeder's replay of revisions filed
        before the check. The viewset never passes it, whatever the payload says."""
        v2 = self._fork()
        _answer(v2, "g6_0_production", "split_operation", True)
        filing = self._create({"commingling_barriers": True})
        res = self.client.post(
            f"{self._base()}{filing.pk}/sign/",
            {"signer_title": "Owner", "compare_plan_versions": False},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:400])
        filing.refresh_from_db()
        self.assertIsNone(filing.signed_at)

    def test_mark_all_unchanged_names_every_section_that_moved_and_what_moved(self):
        v2 = self._fork()
        _answer(v2, "g6_0_production", "split_operation", True)
        _narrative(v2, "recordkeeping_description", "Harvest logs now kept in Trazo, not on paper.")
        PlanMaterialEntry.objects.create(osp=v2, product_name="Gypsum", reason_for_use="Calcium", created_by=self.user)
        filing = self._create(ALL_SIX)

        body = self._sign(filing).json()

        differs = {row["section"]: row["differs"] for row in body["sections"]}
        self.assertEqual(
            differs,
            {
                "inputs_list": ["materials"],
                "recordkeeping_description": ["narrative"],
                "commingling_barriers": ["answers"],
            },
        )
        # Regulation order, the order the card and the certifier read them in.
        self.assertEqual(
            [row["section"] for row in body["sections"]],
            ["inputs_list", "recordkeeping_description", "commingling_barriers"],
        )

    def test_filing_records_what_was_sent_even_when_the_plan_moved_after_signing(self):
        # Filing records a fact (the signed revision reached the agent). Refusing it would leave
        # Trazo saying "not filed" about a revision the agent holds; the check lives at signing.
        v2 = self._fork()
        filing = self._create({"commingling_barriers": True})
        self.assertEqual(self._sign(filing).status_code, status.HTTP_200_OK)
        _answer(v2, "g6_0_production", "split_operation", True)

        res = self._file(filing)

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:600])
        filing.refresh_from_db()
        self.assertIsNotNone(filing.submitted_at)
        # And the conflict is still there for the reader: the same comparison names the section.
        from certifications.services.annual_update_filing import attested_sections_that_differ

        self.assertTrue(attested_sections_that_differ(filing))


class AllowedTests(_Renewal):
    def test_signing_and_filing_go_through_when_no_attested_section_differs(self):
        v2 = self._fork()
        _answer(v2, "g6_0_production", "split_operation", True)
        # Commingling changed and is left unticked; the sections ticked did not change.
        filing = self._create({"practices_procedures": True, "monitoring_plan": True})
        self.assertEqual(filing.new_osp_id, v2.pk)

        self.assertEqual(self._sign(filing).status_code, status.HTTP_200_OK)
        self.assertEqual(self._file(filing).status_code, status.HTTP_200_OK)
        filing.refresh_from_db()
        self.assertIsNotNone(filing.submitted_at)

    def test_a_fork_with_no_edits_lets_every_section_be_attested(self):
        self._fork()
        filing = self._create(ALL_SIX)
        self.assertEqual(self._sign(filing).status_code, status.HTTP_200_OK)
        self.assertEqual(self._file(filing).status_code, status.HTTP_200_OK)

    def test_a_draft_that_attests_a_changed_section_still_saves(self):
        v2 = self._fork()
        _answer(v2, "g6_0_production", "split_operation", True)
        filing = self._create(ALL_SIX)
        res = self.client.patch(
            f"{self._base()}{filing.pk}/",
            {"sections_unchanged_attestation": {**ALL_SIX, "monitoring_plan": False}},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:400])
        filing.refresh_from_db()
        self.assertFalse(filing.sections_unchanged_attestation["monitoring_plan"])
        self.assertTrue(filing.sections_unchanged_attestation["commingling_barriers"])

    def test_an_update_with_no_newer_version_is_not_blocked(self):
        """A first year in Trazo: the plan on file is the only version, so there is nothing to
        compare and the attestation is the grower's statement alone."""
        filing = self._create(ALL_SIX)
        self.assertIsNone(filing.new_osp_id)
        self.assertEqual(self._sign(filing).status_code, status.HTTP_200_OK)
        self.assertEqual(self._file(filing).status_code, status.HTTP_200_OK)
