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
            "given by the operation on the form; this packet signs nothing for it",
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
    """WSDA, reply received by 2026-11-09: the fee form it sends with the renewal application is not the edition on its
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

    def test_the_fee_form_is_named_with_its_reason_and_no_rows(self):
        """Overall review 2026-11, OV-PK-W01. WSDA, reply received by 2026-11-09: "Our fee forms are updated regularly.
        Inputting it in your system would potentially cause an operation to use an outdated form."
        02s itemised lines 1 to 4a of the R 05/26 file; it now names the form with that reason and
        reproduces none of it."""
        osp = self._plan("Washington State Department of Agriculture")
        fee = next(f for f in renewal_routing(osp)[1] if f.document_id == "AGR 2521")
        self.assertEqual((fee.rows, fee.revision, fee.url), ((), "", ""))
        self.assertIn("does not reproduce its items", fee.reason)
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        for name in ("02s-renewal-status-and-routing.pdf", "06-question-index.pdf"):
            text = " ".join(_pdf_text(packet.read(name)).split())
            with self.subTest(document=name):
                self.assertIn(
                    "Washington State Department of Agriculture does not publish it, so this packet does not "
                    "reproduce its items.",
                    text,
                )
                for line in (
                    "Gross annual income received in the last calendar year",
                    "Late fee ($100 for each month after March 1)",
                    "How will you be submitting your application packet",
                    "If submitted separately, when was the application sent",
                    "the rows below were read from an earlier copy",
                ):
                    self.assertNotIn(line, text)

    def test_not_reproduced_needs_a_basis_a_date_and_a_form_filed_with_the_agent(self):
        from certifications.services.certifier_register import _not_reproduced_meta

        self.assertEqual(_not_reproduced_meta({}, "x.yaml"), {})
        with self.assertRaisesMessage(ValueError, "not_reproduced needs a basis and the date it was decided"):
            _not_reproduced_meta({"filed_with_agent": True, "not_reproduced": {"basis": "WSDA said so."}}, "x.yaml")
        with self.assertRaisesMessage(ValueError, "not_reproduced describes a form filed with the agent"):
            _not_reproduced_meta({"not_reproduced": {"basis": "WSDA said so.", "decided": "2026-11-11"}}, "x.yaml")

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
        filing = OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=2026,
            changes_summary="Hedgerow.",
            prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
        )
        file_filing(sign_filing(filing, self.user), "agent_web_form")
        for coverage in form_coverage(osp, "ccof"):
            if coverage.document_id in ("Annual Renewal Contract", "ORGB88"):
                self.assertEqual(coverage.standing, "filed_with_agent", coverage.document_id)

    def test_the_filed_document_does_not_move_when_routing_does(self):
        """Routing lives in 02s. A filed 02 is the bytes that were filed, whatever the register
        says about the agent's forms afterwards."""
        osp = self._plan("CCOF")
        filing = OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=2026,
            changes_summary="Hedgerow.",
            prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
        )
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

    def test_otco_step_5_terms_are_executed_by_the_signature_on_otcos_form(self):
        """Run 3 kept 5-4 off the notify line; since 2026-11-04 (1) to (5) are what they are on the
        form, terms the Step 5 signature executes ("By signing this form, you are stating that:"),
        and the signature row says the packet signs nothing for the operation."""
        osp, rows = self._otco_rows()
        for ref in ("5-1", "5-2", "5-3", "5-4", "5-5"):
            self.assertNotIn(ref, rows)
        signature = rows["Step 5 (signature, date, title)"]
        self.assertEqual(signature.standing, "given by the operation on the form; this packet signs nothing for it")
        self.assertEqual(signature.where, "")

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
                    prior_osp=osp,
                    reporting_year=2026,
                    changes_summary="Hedgerow planted.",
                    created_by=self.user,
                    prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
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
        filing = OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=2026,
            changes_summary="Hedgerow.",
            prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
        )
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


class CertifierFacingWordsTests(_Farm):
    """Renewal audit of CCOF, WSDA and OTCO, read live 2026-11-04. 02s printed the register's own
    notes ("<prior year>", "<date> (<method>)", "the in-app copy sheet gives all three") and called
    every out-of-scope row "the operation's own election", a fee and a signature included."""

    AGENTS = ("CCOF", "Washington State Department of Agriculture", "Oregon Tilth Certified Organic")

    def test_no_placeholder_or_in_app_note_reaches_the_page(self):
        for agent in self.AGENTS:
            with self.subTest(agent=agent):
                osp = self._plan(agent)
                text = self._supplement(osp)
                for word in ("<", ">", "`", "copy sheet", "in-app", "Signed in Trazo by"):
                    self.assertNotIn(word, text, (agent, word))
                osp.delete()

    def test_each_row_prints_what_the_form_asks(self):
        wsda = self._plan("Washington State Department of Agriculture")
        text = self._supplement(wsda)
        wsda.delete()
        self.assertIn("Indicate what changes need to be made for each site", text)
        # The fee form is not reproduced (OV-PK-W01): its items are not printed at all.
        self.assertNotIn("Gross annual income received in the last calendar year.", text)
        # A row named after the form's own label prints the label once.
        ccof = self._supplement(self._plan("CCOF"))
        self.assertIn("Operation Name (required).", ccof)
        self.assertNotIn("Operation Name: Operation Name", ccof)
        # An optional row's standing does not read as an obligation beside "[optional on the form]"
        # (review of back #280).
        self.assertIn(
            "Please enter any comments or questions (optional free text to CCOF). the operation's to answer on "
            "the form [optional on the form]",
            ccof,
        )
        self.assertNotIn("answered by the operation", ccof)

    def test_an_out_of_scope_row_is_worded_by_its_basis(self):
        from certifications.services.packet_coverage import _OUT_OF_SCOPE_WORDS

        expected = {
            # WSDA's fee form rows "2" and "4" stood here until its items stopped being reproduced
            # (overall review 2026-11, OV-PK-W01); OTCO's payment row carries the payment wording now.
            (
                "Oregon Tilth Certified Organic",
                "Step 6 (payment included)",
            ): "an amount the agent sets; entered on the form",
            ("CCOF", "Please enter any comments or questions"): "the operation's to answer on the form",
            ("CCOF", "Step 1: Request Renewal"): "the operation's own election on the form",
            ("Oregon Tilth Certified Organic", "Step 6 (billing contact)"): "the operation's to answer on the form",
        }
        seen = set()
        for agent in self.AGENTS:
            osp = self._plan(agent)
            for form in renewal_routing(osp)[1]:
                for row in form.rows:
                    if (agent, row.ref) in expected:
                        self.assertEqual(row.standing, expected[(agent, row.ref)], (agent, row.ref))
                        seen.add((agent, row.ref))
                    if "election" in row.standing:
                        self.assertEqual(row.standing, _OUT_OF_SCOPE_WORDS["not_an_operation_obligation"])
            osp.delete()
        self.assertEqual(seen, set(expected))

    def test_every_answered_renewal_row_names_where_in_certifier_words(self):
        from certifications.services.certifier_register import load_forms

        for agent in ("ccof", "wsda", "otco"):
            forms = load_forms(agent)
            for form in forms:
                if not form.renewal_role:
                    continue
                for item in form.items:
                    if item.kind == "question" and item.status in ("covered", "partial"):
                        with self.subTest(agent=agent, form=form.title, ref=item.ref):
                            self.assertTrue(item.where, "a covered or partial renewal row needs `trazo.where`")
                            for word in ("<", "`", "copy sheet", "in-app"):
                                self.assertNotIn(word, item.where)

    def test_every_row_the_question_index_falls_back_on_names_where(self):
        """06 prints the register's location when the packet gives nothing else for a row. That was
        the internal `prints` note ("parcel-application-<name>.pdf §E (should also be §A)",
        "`certificate_of_record`"); it is `where` since 2026-11-04, so every row that could reach
        the fallback needs one."""
        from certifications.services.certifier_register import load_forms

        for agent in ("ccof", "wsda", "otco"):
            for form in load_forms(agent):
                for item in form.items:
                    if item.kind != "question" or item.status not in ("covered", "partial"):
                        continue
                    if item.where:
                        for word in ("<", "`", "copy sheet", "in-app", "should also"):
                            self.assertNotIn(word, item.where, (agent, form.title, item.ref))
                    if item.questions:
                        continue
                    prints = " ".join(item.prints.split())
                    if prints and prints not in ("—", "-"):
                        with self.subTest(agent=agent, form=form.title, ref=item.ref):
                            self.assertTrue(item.where, "a row 06 falls back on needs `trazo.where`")

    def test_the_question_index_prints_no_register_note(self):
        for agent in self.AGENTS:
            with self.subTest(agent=agent):
                osp = self._plan(agent)
                zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
                text = _pdf_text(zf.read("06-question-index.pdf"))
                for word in ("<", "`", "should also", "certificate_of_record", "copy sheet", "in-app"):
                    self.assertNotIn(word, text, (agent, word))
                osp.delete()
