"""
What the renewal packet must not say, from three reviewer reads of the same specimen packet (CCOF,
WSDA and OTCO, 2026-11-04), each generated in its own scratch database and read as that agent's
reviewer would on its renewal date.

1. A certificate on file from another agent than the one the plan names. The cover printed it under
   the new agent's renewal routing, and 02s sent the new agent's Cert No and Client ID rows to it.
2. "Yes" to "every input material I use is entered in this list" while the records name products
   the list does not hold, on the same page as the line saying so.
3. A section attested unchanged on the year's filing while the plan versions show its answers
   changed (commingling attested unchanged; split production went from No to Yes).
4. Counts and windows that read as contradictions: "1 deletion entry" beside a deletion that says
   "None", and a plan review "between the newest answer and" the same day.
"""

import io
import zipfile

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate, PlanMaterialEntry
from certifications.osp_modules.materials_application import MATERIALS_APPLICATION
from certifications.services.attestation_gates import blocked_attestations
from certifications.services.operation_certificate import certificate_from_another_agent
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_coverage import renewal_routing
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel
from users.models import User

WSDA = "Washington State Department of Agriculture"
CCOF = "CCOF Certification Services, LLC"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="truth@test.com", password="x", first_name="Ira", last_name="Vale")
        self.company = Company.objects.create(name="Truth Orchards LLC")
        self.est = Establishment.objects.create(name="Truth Orchard", company=self.company, contact_person="Ira Vale")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(
            name="Pears 2026", start_date=timezone.now(), parcel=self.parcel, operator=self.user
        )

    def _plan(self, certifier, version=1, status="active", **fields):
        return OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=version, status=status, certifier_name=certifier, **fields
        )

    def _file(self, name, osp):
        return _pdf_text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp))).read(name))

    def _answer(self, osp, module, **answers):
        responses = osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module] = {"answers": {k: {"value": v} for k, v in answers.items()}}
        osp.module_responses = responses
        osp.save(update_fields=["module_responses"])


class CertificateFromAnotherAgentTests(_Farm):
    def _moving(self, agent="Cascadia Organic Certifiers"):
        return self._plan(WSDA, approval_certificate_number="COC-1463", approval_certifier_name=agent)

    def test_it_is_found_only_when_another_agent_issued_the_certificate(self):
        osp = self._moving()
        other = certificate_from_another_agent(osp)
        self.assertEqual((other.certificate.number, other.confirmed), ("COC-1463", False))
        osp.approval_certifier_name = CCOF
        osp.save(update_fields=["approval_certifier_name"])
        self.assertTrue(certificate_from_another_agent(osp).confirmed)
        osp.approval_certifier_name = WSDA
        osp.save(update_fields=["approval_certifier_name"])
        self.assertIsNone(certificate_from_another_agent(osp))
        osp.approval_certificate_number = ""
        osp.approval_certifier_name = "Cascadia Organic Certifiers"
        osp.save(update_fields=["approval_certificate_number", "approval_certifier_name"])
        self.assertIsNone(certificate_from_another_agent(osp))

    def test_a_known_other_agent_is_stated_as_another_agent(self):
        osp = self._moving(agent=CCOF)
        sentence = (
            f"This certificate was issued by {CCOF}. The plan names Washington State "
            "Department of Agriculture as its certifying agent, which did not issue it."
        )
        self.assertIn(sentence, self._file("00-cover.pdf", osp))
        self.assertIn(sentence, self._file("02s-renewal-status-and-routing.pdf", osp))

    def test_a_name_trazo_cannot_match_is_never_stated_as_another_agent(self):
        """Review of back #284: "CCOF Inc." may be the plan's own agent spelled another way."""
        osp = self._moving()
        cover = self._file("00-cover.pdf", osp)
        self.assertIn(
            "This certificate names Cascadia Organic Certifiers as its certifying agent and the plan names "
            "Washington State Department of Agriculture; Trazo does not recognise the first name, so it cannot "
            "say whether they are the same agent.",
            cover,
        )
        self.assertNotIn("which did not issue it", cover)

    def test_the_new_agents_cert_no_row_says_the_certificate_is_another_agents(self):
        osp = self._moving()
        fee = next(f for f in renewal_routing(osp)[1] if f.document_id == "AGR 2521")
        header = next(r for r in fee.rows if r.ref.startswith("Header"))
        self.assertIn("the certificate on the cover names Cascadia Organic Certifiers", header.where)

    def test_a_client_id_row_is_not_sent_to_a_cover_that_prints_none(self):
        osp = self._plan(CCOF)
        contract = next(f for f in renewal_routing(osp)[1] if f.title == "Annual Renewal Contract")
        row = next(r for r in contract.rows if r.ref == "Client Code")
        self.assertEqual(
            row.standing, "not in this packet; answer it on the form (no Client ID is recorded for this agent)"
        )
        self.assertEqual(row.where, "")
        self.est.certifier_client_id, self.est.certifier_client_id_agent = "C-4471", "ccof"
        self.est.save()
        contract = next(f for f in renewal_routing(osp)[1] if f.title == "Annual Renewal Contract")
        row = next(r for r in contract.rows if r.ref == "Client Code")
        self.assertEqual((row.standing, row.where), ("in this packet", "00-cover.pdf: Client ID"))


class MaterialsReconciliationGateTests(_Farm):
    def _apply(self, name, type_code="PE"):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=self.history, date=timezone.now(), description="spray", type=type_code, commercial_name=name
            )

    def _list(self, name, category="pest_disease_weed"):
        PlanMaterialEntry.objects.create(
            osp=self.osp, product_name=name, category=category, listing_basis=PlanMaterialEntry.BASIS_NONE
        )

    def setUp(self):
        super().setUp()
        self.osp = self._plan(WSDA, status="draft")

    def test_yes_is_refused_while_the_records_name_a_product_the_list_does_not_hold(self):
        self._list("Entrust SC")
        self._apply("Entrust SC")
        self._apply("Kocide 3000", type_code="FU")
        blocked = blocked_attestations(
            MATERIALS_APPLICATION, {"materials_list_complete": True, "pest_disease_weed_listed": True}, self.osp
        )
        self.assertIn("materials_list_complete", blocked)
        self.assertIn("Kocide 3000", blocked["pest_disease_weed_listed"])
        self._list("Kocide 3000")
        self.assertEqual(
            blocked_attestations(
                MATERIALS_APPLICATION, {"materials_list_complete": True, "pest_disease_weed_listed": True}, self.osp
            ),
            {},
        )

    def test_a_category_statement_is_refused_only_over_its_own_products(self):
        self._apply("Fish Emulsion 5-1-1", type_code="FE")
        self.assertEqual(blocked_attestations(MATERIALS_APPLICATION, {"pest_disease_weed_listed": True}, self.osp), {})
        self.assertIn(
            "fertilizers_listed",
            blocked_attestations(MATERIALS_APPLICATION, {"fertilizers_listed": True}, self.osp),
        )

    def test_a_grower_who_applies_nothing_can_still_say_yes(self):
        self.assertEqual(blocked_attestations(MATERIALS_APPLICATION, {"materials_list_complete": True}, self.osp), {})

    def test_no_is_never_refused(self):
        self._apply("Kocide 3000", type_code="FU")
        self.assertEqual(blocked_attestations(MATERIALS_APPLICATION, {"materials_list_complete": False}, self.osp), {})


class UnchangedButChangedTests(_Farm):
    def test_02s_names_a_section_attested_unchanged_whose_answers_changed_and_only_that_one(self):
        prior = self._plan(WSDA, version=1, status="superseded")
        self._answer(prior, "g6_0_production", split_operation=False)
        new = self._plan(WSDA, version=2, status="active")
        self._answer(new, "g6_0_production", split_operation=True)
        OSPAnnualUpdate.objects.create(
            prior_osp=prior,
            new_osp=new,
            reporting_year=timezone.localdate().year + 1,
            changes_summary="Started a conventional block.",
            sections_unchanged_attestation={"commingling_barriers": True, "practices_procedures": True},
            created_by=self.user,
        )
        text = self._file("02s-renewal-status-and-routing.pdf", new)
        self.assertIn("Sections attested unchanged whose answers changed", text)
        self.assertIn("between plan v1 and v2", text)
        self.assertIn("§ 205.201(a)(5)", text[text.index("Sections attested unchanged whose") :][:600])
        # split_operation compiles into (a)(5) only: (a)(1) is not called changed.
        self.assertNotIn("§ 205.201(a)(1)", text[text.index("Sections attested unchanged whose") :][:600])


class CoverCountTests(_Farm):
    def test_a_deletion_that_states_none_says_so(self):
        osp = self._plan(WSDA)
        OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=timezone.localdate().year + 1,
            changes_summary="No changes.",
            additions=["Hedgerow along the north edge"],
            deletions=["None. No input or practice was dropped."],
            created_by=self.user,
        )
        text = self._file("00-cover.pdf", osp)
        self.assertIn("Entries under (a)(2): 1 addition entry, 1 deletion entry, stating none", text)


class EmptyReviewWindowTests(TestCase):
    """Review of back #284: each date in the sentence is printed as what it is."""

    def _sentence(self, newest, end):
        from types import SimpleNamespace

        from certifications.services.osp_module_pdf import _empty_review_window_sentence

        return _empty_review_window_sentence(SimpleNamespace(answers_as_of=newest, reference_date=end))

    def test_the_same_day(self):
        self.assertEqual(
            self._sentence("2026-08-21", "2026-08-21"),
            "The plan's newest answer is dated 2026-08-21, the date this review runs to, so there is no later "
            "period to check.",
        )

    def test_an_answer_newer_than_the_review_names_both_dates(self):
        text = self._sentence("2026-09-03", "2026-08-21")
        self.assertIn("newest answer (2026-09-03) is later than the date this review runs to (2026-08-21)", text)
