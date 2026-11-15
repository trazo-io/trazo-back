"""A grower's first year on Trazo: the certifier holds a plan Trazo has never seen.

WHY THIS EXISTS
---------------
Overall review 2026-11, OV-PK-C01 / OV-PK-W03 / OV-PK-O02 (P1, every pilot grower): Trazo's change
list compares two Trazo plan versions. In a grower's first year the plan the certifier holds is the
one filed before Trazo, on the certifier's own forms, and Trazo has no copy of it. The annual-update
card still said "This filing continues OSP v1, the plan your certifier holds", and the packet's
empty comparison read as "nothing changed".

Status cannot tell the two cases apart: a plan goes active on the certificate the grower already
holds for the old plan. So a filing that continues the first plan version in Trazo says which it is
(`OSPAnnualUpdate.prior_plan_basis`), by the time it is signed. A draft first version was never
sent, so the server answers for it. When the certifier holds the plan filed before Trazo, the
cover, 02 and 02s say so for every agent, the changed-sections packet is refused with its own
reason, and the copy sheet says why there is no list.
"""

import io
import json
import re
import zipfile
from datetime import datetime
from datetime import timezone as dt_tz

from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.agent_form_sheet import agent_form_sheet
from certifications.services.annual_update_filing import (
    PRIOR_PLAN_BASIS_REQUIRED,
    correct_filing,
    file_filing,
    sign_filing,
)
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_coverage import packet_agent
from certifications.services.packet_scope import scope_preview
from company.models import Company, Establishment
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text

AGENT_FILE = OSPAnnualUpdate.PRIOR_BASIS_AGENT_FILE
TRAZO_VERSION = OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION
OTCO = "Oregon Tilth Certified Organic"
CCOF = "CCOF"
WSDA = "Washington State Department of Agriculture"
# The no-verdict rule every printed packet sentence keeps (test_packet_wording_follows_records).
_VERDICT = re.compile(r"non-?\s?complian|non-?\s?conformance|will be flagged", re.IGNORECASE)


class _FirstYear(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="firstyear@test.com", password="x", is_verified=True, first_name="Rosa", last_name="Lind"
        )
        self.company = Company.objects.create(name="First Year Orchards LLC")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="First Year Orchard", company=self.company)
        self.client.force_authenticate(user=self.user)

    def _plan(self, *, status_="active", certifier=OTCO, version=1, previous=None):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=version,
            status=status_,
            certifier_name=certifier,
            previous_version=previous,
            submitted_at=None if status_ == "draft" else datetime(2026, 1, 10, tzinfo=dt_tz.utc),
        )

    def _base(self):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osp-annual-updates/"

    def _create(self, prior, **extra):
        return self.client.post(
            self._base(),
            {
                "prior_osp": prior.pk,
                "reporting_year": 2027,
                "changes_summary": "Added a hedgerow along the north block.",
                **extra,
            },
            format="json",
        )

    def _created(self, prior, **extra) -> OSPAnnualUpdate:
        res = self._create(prior, **extra)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        return OSPAnnualUpdate.objects.get(pk=res.json()["id"])

    def _sign(self, filing):
        return self.client.post(f"{self._base()}{filing.pk}/sign/", {"signer_title": "Owner"}, format="json")


class AskedOfAFirstVersionTests(_FirstYear):
    def test_signing_is_refused_until_the_filing_says_what_the_certifier_holds(self):
        v1 = self._plan()
        res = self._create(v1)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        self.assertEqual(res.json()["prior_plan_basis"], "")
        self.assertTrue(res.json()["basis_question_applies"])
        filing = OSPAnnualUpdate.objects.get(pk=res.json()["id"])

        res = self._sign(filing)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:500])
        body = res.json()
        self.assertEqual(
            (body["code"], body["action"], body["prior_osp_version"]), (PRIOR_PLAN_BASIS_REQUIRED, "sign", 1)
        )
        self.assertIn("Not signed.", body["detail"])
        self.assertIn("first plan version in Trazo", body["detail"])
        filing.refresh_from_db()
        self.assertIsNone(filing.signed_at)

    def test_either_answer_signs(self):
        for basis in (AGENT_FILE, TRAZO_VERSION):
            with self.subTest(basis=basis):
                OSPAnnualUpdate.objects.all().delete()
                OrganicSystemPlan.objects.all().delete()
                filing = self._created(self._plan(), prior_plan_basis=basis)
                res = self._sign(filing)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:500])
                filing.refresh_from_db()
                self.assertEqual(filing.prior_plan_basis, basis)
                self.assertEqual(filing.signed_content()["prior_plan_basis"], basis)

    def test_saving_a_draft_without_the_answer_is_never_refused(self):
        filing = self._created(self._plan())
        res = self.client.patch(
            f"{self._base()}{filing.pk}/", {"changes_summary": "Added a hedgerow and a bee strip."}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:500])


class AnsweredByTheServerTests(_FirstYear):
    def test_a_draft_first_version_was_never_sent_so_the_certifier_holds_the_plan_filed_before_trazo(self):
        v1 = self._plan(status_="draft")
        res = self._create(v1)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        self.assertEqual(res.json()["prior_plan_basis"], AGENT_FILE)
        self.assertFalse(res.json()["basis_question_applies"])
        self.assertEqual(self._sign(OSPAnnualUpdate.objects.get(pk=res.json()["id"])).status_code, status.HTTP_200_OK)

    def test_a_draft_first_version_cannot_be_called_the_plan_the_certifier_received(self):
        res = self._create(self._plan(status_="draft"), prior_plan_basis=TRAZO_VERSION)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:500])
        self.assertIn("prior_plan_basis", res.json())

    def test_a_later_version_is_compared_between_trazo_versions_and_never_asked(self):
        v1 = self._plan(status_="superseded")
        v2 = self._plan(version=2, previous=v1)
        res = self._create(v2, prior_plan_basis=AGENT_FILE)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:500])
        self.assertIn("prior_plan_basis", res.json())

        res = self._create(v2)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        self.assertFalse(res.json()["basis_question_applies"])
        self.assertEqual(self._sign(OSPAnnualUpdate.objects.get(pk=res.json()["id"])).status_code, status.HTTP_200_OK)


class SignatureTests(_FirstYear):
    def test_a_filing_with_no_answer_hashes_exactly_as_before_the_question_existed(self):
        """Hashed only when stated: every revision signed before 2026-11-14 keeps its signature."""
        filing = self._created(self._plan())
        self.assertNotIn("prior_plan_basis", filing.signed_content())
        legacy = {name: getattr(filing, name) for name in OSPAnnualUpdate.SIGNED_FIELDS}
        import hashlib

        expected = hashlib.sha256(
            json.dumps(legacy, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        self.assertEqual(filing.content_sha256(), expected)

    def test_the_answer_is_signed_and_carried_into_a_correction(self):
        filing = self._created(self._plan(), prior_plan_basis=AGENT_FILE)
        filing = sign_filing(filing, self.user)
        signed = filing.signed_content_sha256
        filing.prior_plan_basis = TRAZO_VERSION
        self.assertNotEqual(filing.content_sha256(), signed, "changing the answer must break the signature")
        filing.refresh_from_db()
        file_filing(filing, filing_method="email", user=self.user)

        correction = correct_filing(filing, self.user)

        self.assertEqual(correction.prior_plan_basis, AGENT_FILE)


class PrintedTests(_FirstYear):
    def _packet(self, osp) -> dict:
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(OrganicSystemPlan.objects.get(pk=osp.pk))))
        return {
            name: _pdf_text(zf.read(name))
            for name in ("00-cover.pdf", "02-annual-update.pdf", "02s-renewal-status-and-routing.pdf")
        }

    def test_every_agent_reads_that_trazo_holds_no_copy_of_the_plan_on_file(self):
        for certifier in (OTCO, CCOF, WSDA):
            with self.subTest(certifier=certifier):
                OSPAnnualUpdate.objects.all().delete()
                OrganicSystemPlan.objects.all().delete()
                v1 = self._plan(certifier=certifier)
                self._created(
                    v1,
                    prior_plan_basis=AGENT_FILE,
                    sections_unchanged_attestation={"monitoring_plan": True},
                )
                agent = packet_agent(v1).name
                docs = self._packet(v1)
                cover, filing, supplement = (
                    docs["00-cover.pdf"],
                    docs["02-annual-update.pdf"],
                    docs["02s-renewal-status-and-routing.pdf"],
                )

                self.assertIn("first plan version in Trazo", cover)
                self.assertIn("has no copy of that plan, so this packet lists no changes against it", cover)
                self.assertIn("not a comparison Trazo made", filing)
                self.assertIn(f"Sections attested unchanged since the plan on file with {agent}", filing)
                self.assertIn(f"Changes against the plan on file with {agent}", supplement)
                self.assertIn("so this packet cannot list which sections changed against it", supplement)
                self.assertIn(f"on {agent}'s own forms", supplement)
                if certifier == OTCO:
                    self.assertIn("None listed from Trazo", supplement)
                for name, text in docs.items():
                    self.assertIsNone(_VERDICT.search(text), name)

    def test_a_plan_the_certifier_received_from_trazo_reads_as_before(self):
        v1 = self._plan()
        self._created(v1, prior_plan_basis=TRAZO_VERSION)
        agent = packet_agent(v1).name
        docs = self._packet(v1)

        self.assertIn(f"{agent} received plan v1 from Trazo", docs["02-annual-update.pdf"])
        for name, text in docs.items():
            self.assertNotIn("first plan version in Trazo", text, name)
        self.assertIn("did not create a new plan version", docs["02s-renewal-status-and-routing.pdf"])

    def test_a_filing_that_never_answered_prints_nothing_it_did_not_state(self):
        """Filings signed before the question existed: nothing is inferred for them."""
        v1 = self._plan()
        self._created(v1)
        for name, text in self._packet(v1).items():
            self.assertNotIn("first plan version in Trazo", text, name)
            self.assertNotIn("Changes against the plan on file", text, name)


class ScopeAndSheetTests(_FirstYear):
    def test_the_changed_sections_packet_names_the_first_version_as_its_reason(self):
        v1 = self._plan()
        self._created(v1, prior_plan_basis=AGENT_FILE)
        preview = scope_preview(OrganicSystemPlan.objects.get(pk=v1.pk))
        self.assertEqual((preview["available"], preview["code"]), (False, "first_version"))
        self.assertIn("Trazo has no copy of that plan", preview["reason"])

    def test_otco_step_4_and_new_land_say_first_version(self):
        v1 = self._plan()
        self._created(v1, prior_plan_basis=AGENT_FILE)
        rows = {row["item"]: row for row in agent_form_sheet(OrganicSystemPlan.objects.get(pk=v1.pk))["rows"]}
        self.assertEqual(
            (rows["osp_changes"]["kind"], rows["osp_changes"]["extra"]["state"]), ("yours", "first_version")
        )
        self.assertEqual(rows["new_land"]["extra"]["reason"], "first_version")

    def test_ccof_step_2_carries_the_first_version_flag(self):
        for basis, expected in ((AGENT_FILE, True), (TRAZO_VERSION, False)):
            with self.subTest(basis=basis):
                OSPAnnualUpdate.objects.all().delete()
                OrganicSystemPlan.objects.all().delete()
                v1 = self._plan(certifier=CCOF)
                self._created(v1, prior_plan_basis=basis)
                rows = {r["item"]: r for r in agent_form_sheet(OrganicSystemPlan.objects.get(pk=v1.pk))["rows"]}
                self.assertIs(rows["ccof_osp_update"]["extra"]["first_version"], expected)


class LeavingDraftTests(_FirstYear):
    """Review of back #431: the server's answer for a draft first version does not outlive the draft."""

    _NARRATIVE = (
        "The three blocks are on raised beds with sawdust mulch and drip; the ground runs a four-year rotation "
        "with a winter cover of cereal rye, hairy vetch and crimson clover drilled in October and terminated in "
        "March. Inputs come only from the approved materials list, each delivery checked against it when it "
        "lands. Records are kept in Trazo as the work happens and reviewed before each renewal goes out."
    )

    def _draft_v1(self):
        from certifications.models import OSP_SECTION_KEYS

        v1 = self._plan(status_="draft")
        v1.sections = {key: {"narrative_manual": f"Section {key}: {self._NARRATIVE}"} for key in OSP_SECTION_KEYS}
        v1.save(update_fields=["sections"])
        return v1

    def test_submitting_the_first_version_asks_again_before_signing(self):
        v1 = self._draft_v1()
        filing = self._created(v1)
        self.assertEqual(filing.prior_plan_basis, AGENT_FILE)

        res = self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{v1.pk}/submit/", {}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:500])

        filing.refresh_from_db()
        self.assertEqual(filing.prior_plan_basis, "")
        res = self._sign(filing)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:500])
        self.assertEqual(res.json()["code"], PRIOR_PLAN_BASIS_REQUIRED)

    def test_a_filing_signed_while_the_plan_was_a_draft_keeps_its_answer(self):
        v1 = self._draft_v1()
        filing = self._created(v1)
        self.assertEqual(self._sign(filing).status_code, status.HTTP_200_OK)

        res = self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{v1.pk}/submit/", {}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:500])

        filing.refresh_from_db()
        self.assertEqual(filing.prior_plan_basis, AGENT_FILE)
        self.assertEqual(filing.content_sha256(), filing.signed_content_sha256)
