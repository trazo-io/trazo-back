"""A renewal packet routes the operation to its OWN agent's renewal forms, and to no one else's.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, T20 (AUDIT.md §5). The packet carried the operation's § 205.406(a)
record and said it "supports, and does not replace" the agent's own renewal form, without naming
that form. CCOF had no renewal form in the register at all, WSDA's fee form (AGR 2521) was neither
registered nor excluded, and CCOF's Crop Update (NOPB88) was a known gap. A reviewer had to work
out which agent paperwork the year's renewal still needed.

Since 2026-10-01 the renewal supplement (02s) lists each agent's renewal forms, with a row-by-row
crosswalk to where the answer is in the packet. The forms are still filed with the agent: listing
one never makes it read as answered.
"""

import io
import zipfile
from datetime import datetime
from datetime import timezone as dt_tz

from django.test import TestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.annual_update_filing import file_filing, sign_filing
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_coverage import form_coverage, renewal_routing
from company.models import Company, Establishment
from users.models import User

from .test_renewal_packet_contents import _pdf_text

#: The renewal forms each registered agent's 02s must name, by the title the page prints.
EXPECTED = {
    "CCOF": {"Annual Renewal Contract", "Crop Update (NOPB88)"},
    "Oregon Tilth Certified Organic": {"Organic System Plan Update Application & Agreement (OSP Update Form)"},
    "Washington State Department of Agriculture": {
        "Annual Renewal Application (Renewal application)",
        "Site Update Information (AGR 2516)",
        "Renewal Fee Form (AGR 2521)",
    },
}
ALL_TITLES = set().union(*EXPECTED.values())


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="route@test.com", password="x", first_name="Dana", last_name="Router"
        )
        self.company = Company.objects.create(name="Routing Orchards LLC")
        self.est = Establishment.objects.create(name="Routing Orchard", company=self.company)

    def _plan(self, certifier):
        return OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", approval_certifier_name=certifier
        )

    def _supplement(self, osp) -> str:
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        return _pdf_text(zf.read("02s-renewal-status-and-routing.pdf"))


class EachAgentGetsItsOwnFormsTests(_Farm):
    def test_each_registered_agent_names_exactly_its_own_renewal_forms(self):
        for agent, expected in EXPECTED.items():
            with self.subTest(agent=agent):
                osp = self._plan(agent)
                text = self._supplement(osp)
                for title in expected:
                    self.assertIn(title, text, (agent, title))
                for title in ALL_TITLES - expected:
                    self.assertNotIn(title, text, (agent, title))
                osp.delete()

    def test_a_fallback_agent_is_routed_to_no_borrowed_form(self):
        """OCI has no register. Its packet borrows CCOF's coverage page shape, but it must not
        send an OCI operation to CCOF's renewal contract (the T23 rule)."""
        osp = self._plan("Organic Certifiers, Inc.")
        self.assertEqual(renewal_routing(osp)[1], [])
        text = self._supplement(osp)
        for title in ALL_TITLES:
            self.assertNotIn(title, text)
        self.assertIn("filed with it directly", text)

    def test_each_question_row_says_where_its_answer_is_or_that_the_form_asks_it(self):
        osp = self._plan("CCOF")
        forms = {f.title: f for f in renewal_routing(osp)[1]}
        contract = forms["Annual Renewal Contract"]
        by_ref = {row.ref: row for row in contract.rows}
        self.assertEqual(by_ref["Operation Name"].standing, "in this packet")
        self.assertIn("00-cover.pdf", by_ref["Operation Name"].where)
        self.assertEqual(
            by_ref["CCOF's Terms of Use and Privacy Policy"].standing,
            "not in this packet; answer it on the form",
        )
        self.assertEqual(by_ref["Step 1: Request Renewal"].standing, "the operation's own election on the form")
        # Instruction rows (the numbered terms) are executed on the form, not answered here.
        self.assertNotIn("1", by_ref)

    def test_an_unpublished_renewal_form_is_named_with_its_reason_and_no_rows(self):
        osp = self._plan("Washington State Department of Agriculture")
        application = next(f for f in renewal_routing(osp)[1] if f.title == "Annual Renewal Application")
        self.assertEqual(application.rows, ())
        self.assertIn("by March 1", application.reason)


class RoutingNeverAnswersTheAgentsFormTests(_Farm):
    def test_a_filed_update_never_makes_a_renewal_form_answered(self):
        osp = self._plan("CCOF")
        filing = OSPAnnualUpdate.objects.create(prior_osp=osp, reporting_year=2026, changes_summary="Hedgerow.")
        file_filing(sign_filing(filing, self.user), "agent_web_form")
        for coverage in form_coverage(osp, "ccof"):
            if coverage.document_id in ("Annual Renewal Contract", "NOPB88"):
                self.assertEqual(coverage.standing, "filed_with_agent", coverage.document_id)

    def test_the_filed_document_does_not_move_when_routing_does(self):
        """Routing lives in 02s. A filed 02 is the bytes that were filed, whatever the register
        says about the agent's forms afterwards."""
        osp = self._plan("CCOF")
        filing = OSPAnnualUpdate.objects.create(prior_osp=osp, reporting_year=2026, changes_summary="Hedgerow.")
        filing = file_filing(sign_filing(filing, self.user), "agent_web_form", datetime(2026, 8, 21, tzinfo=dt_tz.utc))
        frozen = bytes(filing.filed_pdf)
        osp.approval_certifier_name = "Washington State Department of Agriculture"
        osp.save(update_fields=["approval_certifier_name"])
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        self.assertEqual(zf.read("02-annual-update.pdf"), frozen)
        self.assertIn("Renewal Fee Form (AGR 2521)", _pdf_text(zf.read("02s-renewal-status-and-routing.pdf")))
