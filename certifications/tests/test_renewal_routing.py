"""A renewal packet routes the operation to its OWN agent's renewal forms, and to no one else's.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, T20 (AUDIT.md §5). The packet carried the operation's § 205.406(a)
record and said it "supports, and does not replace" the agent's own renewal form, without naming
that form. CCOF had no renewal form in the register at all, WSDA's fee form (AGR 2521) was neither
registered nor excluded, and CCOF's Crop Update (ORGB88) was a known gap. A reviewer had to work
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
    "CCOF": {"Annual Renewal Contract", "Crop Update (ORGB88)"},
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


class AgentSentFormTests(_Farm):
    """WSDA, 2026-10-26: the fee form it sends with the renewal application is not the edition on its
    website ("R 05/26 2521 is not the renewal fee form version we sent to our operations"). The page
    must not send a grower to the website copy."""

    def test_the_fee_form_names_no_edition_and_says_to_fill_in_the_copy_wsda_sent(self):
        text = " ".join(self._supplement(self._plan("Washington State Department of Agriculture")).split())
        self.assertIn("Renewal fee: Renewal Fee Form (AGR 2521)", text)
        self.assertNotIn("Renewal Fee Form (AGR 2521), R 05/26", text)
        self.assertIn(
            "Washington State Department of Agriculture sends this form with its renewal application and updates "
            "it regularly. Fill in the copy Washington State Department of Agriculture sent",
            text,
        )
        self.assertIn("Site update: Site Update Information (AGR 2516), R 01/20", text, "a published form keeps it")

    def test_a_published_form_is_not_marked_as_sent(self):
        forms = renewal_routing(self._plan("Washington State Department of Agriculture"))[1]
        sent = {f.document_id for f in forms if f.sent_with_renewal}
        self.assertEqual(sent, {"AGR 2521"})

    def test_sent_with_renewal_is_only_for_a_renewal_form(self):
        from certifications.services.certifier_register import _filing_meta

        with self.assertRaisesMessage(ValueError, "sent_with_renewal describes a form in the agent's renewal"):
            _filing_meta({"filed_with_agent": True, "sent_with_renewal": "WSDA said so."}, "x.yaml")


class RoutingNeverAnswersTheAgentsFormTests(_Farm):
    def test_a_filed_update_never_makes_a_renewal_form_answered(self):
        osp = self._plan("CCOF")
        filing = OSPAnnualUpdate.objects.create(prior_osp=osp, reporting_year=2026, changes_summary="Hedgerow.")
        file_filing(sign_filing(filing, self.user), "agent_web_form")
        for coverage in form_coverage(osp, "ccof"):
            if coverage.document_id in ("Annual Renewal Contract", "ORGB88"):
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


class Run3RenewalMeaningTests(_Farm):
    """Run 3 (2026-10-02): a row is covered only by the promise it asks for, and a subtotal is never a
    fee figure (R3-02, R3-03, part of R3-08)."""

    def _otco_rows(self):
        osp = self._plan("Oregon Tilth Certified Organic")
        form = next(f for f in renewal_routing(osp)[1] if f.document_id == "OSP Update Form" or "OSP Update" in f.title)
        return osp, {row.ref: row for row in form.rows}

    def test_otco_step_5_4_is_answered_on_otcos_form_not_by_the_notify_line(self):
        osp, rows = self._otco_rows()
        self.assertEqual(rows["5-4"].standing, "not in this packet; answer it on the form")
        self.assertEqual(rows["5-4"].where, "")
        self.assertNotIn("205.400(f)", rows["5-4"].where)

    def test_otco_step_6_points_at_the_subtotal_02_prints(self):
        osp, rows = self._otco_rows()
        row = rows["Step 6 (gross organic sales and period)"]
        self.assertEqual(row.standing, "in part in this packet")
        self.assertIn("02-annual-update.pdf", row.where)
        self.assertIn("Sales records subtotal", row.where)
        self.assertNotIn("none of the packet's documents", row.where)

    def test_the_routing_heading_says_to_file_never_filed(self):
        text = self._supplement(self._plan("CCOF"))
        self.assertIn("Renewal routing: forms to file with the certifying agent", text)
        self.assertNotIn("Renewal forms filed with", text)

    def test_the_subtotal_names_only_this_operations_agent(self):
        """The fee-basis sentence names the operation's own agent's form, never another agency's
        (review of back #91)."""
        from certifications.services.annual_update_filing import file_filing, sign_filing

        for agent, own, foreign in (
            ("Washington State Department of Agriculture", "AGR 2521", ("Oregon Tilth", "Step 6")),
            ("Oregon Tilth Certified Organic", "Step 6", ("AGR 2521", "WSDA")),
            ("CCOF", "fee form sets its own basis", ("AGR 2521", "Oregon Tilth", "Step 6")),
            ("Organic Certifiers, Inc.", "fee form sets its own basis", ("AGR 2521", "Oregon Tilth", "Step 6")),
        ):
            with self.subTest(agent=agent):
                osp = self._plan(agent)
                filing = OSPAnnualUpdate.objects.create(
                    prior_osp=osp, reporting_year=2026, changes_summary="Hedgerow planted.", created_by=self.user
                )
                text = _pdf_text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp))).read("02-annual-update.pdf"))
                self.assertIn("not any certifying agent's fee figure", text)
                self.assertIn(own, text)
                for name in foreign:
                    self.assertNotIn(name, text)
                filing.delete()
                osp.delete()

    def test_a_neutral_frozen_filing_exported_for_otco_gets_otcos_caveat_on_02s(self):
        """Run 4, R4-04: 02 is frozen as filed and may name no agent; the routing page, which follows
        the export, carries the agent's sales-figure caveat."""
        from certifications.services.annual_update_filing import file_filing, sign_filing

        osp = self._plan("Organic Certifiers, Inc.")
        filing = OSPAnnualUpdate.objects.create(prior_osp=osp, reporting_year=2026, changes_summary="Hedgerow.")
        filing = file_filing(sign_filing(filing, self.user, signer_title="Owner"), filing_method="email")
        osp.approval_certifier_name = "Oregon Tilth Certified Organic"
        osp.save(update_fields=["approval_certifier_name"])
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        filed = _pdf_text(packet.read("02-annual-update.pdf"))
        self.assertNotIn("Step 6", filed, "the frozen filing is not rewritten")
        routing = _pdf_text(packet.read("02s-renewal-status-and-routing.pdf"))
        self.assertIn("Sales figure: the subtotal printed on 02", routing)
        self.assertIn("including products not sold as organic", routing)
        self.assertIn("written petition", routing)
        self.assertNotIn("AGR 2521", routing)
