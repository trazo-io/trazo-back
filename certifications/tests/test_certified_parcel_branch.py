"""A currently certified parcel follows its certifier's own branch (OSP alignment audit T21-F1).

WHY THIS EXISTS
---------------
The Calapooia specimen showed a certified parcel's page printing "the operation's own period ...
is not covered: the operator has made no declaration", while the same page said the declaration is
not asked of a certified parcel. The page demanded a statement the form skips.

The fix follows each agent's route (CCOF ORGB49 F2 to G; WSDA AGR 2264 only for new sites and
transfers; OTCO C2 only for new applications and added acreage) and states, item by item, what is
attached, referenced separately or missing. It never manufactures the skipped declaration from
"currently certified", never counts the operator's no-lapse checkbox as verification, and never
says "verified" or "eligible". The wizard payload and the PDF print one assessment.
"""

import io
import re
from datetime import timedelta

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from pdfminer.high_level import extract_text

from certifications.models import Certification, LandownerAffidavit, OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services import certified_parcel_branch as cpb
from certifications.services.osp_module_pdf import _coverage_pdf, generate_module_pdf
from certifications.services.packet_coverage import form_coverage
from certifications.services.parcel_land_history import land_history_summary
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import ChemicalEvent, Production
from product.models import Parcel, ParcelCropHistory, Product
from product.services.parcel_application_status import parcel_application_status, parcel_evidence_status

AGENT_NAMES = {
    "ccof": "CCOF Certification Services, LLC",
    "wsda": "Washington State Department of Agriculture",
    "otco": "Oregon Tilth Certified Organic",
    "oci": "Organic Certifiers, Inc.",
    "mosa": "Midwest Organic Services Association, Inc.",
}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Certified(TestCase):
    agent = "ccof"
    #: The agent the operator names as certifying the parcel. For CCOF it is another agent: a parcel
    #: already on the operation's CCOF file changes on the Crop Update and never reaches F2 (run 3,
    #: R3-04), so F2 to G is exercised with a parcel new to CCOF.
    parcel_certifier = {"ccof": "otco"}

    def setUp(self):
        self.today = timezone.now().date()
        self.company = Company.objects.create(name="Branch Farms LLC")
        self.est = Establishment.objects.create(name="Branch Farm", company=self.company, state="CA")
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="CERT-1",
            certifier_name=AGENT_NAMES[self.agent],
            usda_operation_name="Branch Farms LLC",
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=AGENT_NAMES[self.agent]
        )
        self.parcel = Parcel.objects.create(
            name="North Block",
            establishment=self.est,
            area=4.0,
            date_began_managing=self.today - relativedelta(years=8),
            application_answers={
                "currently_certified": "yes",
                "prior_certifier_name": AGENT_NAMES[self.parcel_certifier.get(self.agent, self.agent)],
                "no_lapse_attested": True,
            },
        )

    def _answer(self, **answers):
        self.parcel.application_answers = {**self.parcel.application_answers, **answers}
        self.parcel.save(update_fields=["application_answers"])

    def _upload(self, section, title):
        return GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=self.parcel,
            source="upload",
            folder="organic_system_plan",
            title=title,
            file=ContentFile(b"%PDF-1.4 evidence", name=f"{title}.pdf"),
            size_bytes=17,
            linked_section=section,
        )

    def _assessment(self):
        return cpb.assess(self.parcel, self.agent)

    def _states(self):
        return {i.key: i.state for i in self._assessment().items}

    def _page(self):
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))


class CcofCertifiedBranchTests(_Certified):
    def test_complete_supporting_documents_are_attached_and_named(self):
        self._upload(cpb.CERTIFICATE_SECTION, "certificate")
        self._upload(cpb.CONTINUITY_SECTION, "ccof-letter")
        states = self._states()
        self.assertEqual(states[cpb.CERTIFICATE], cpb.ATTACHED)
        self.assertEqual(states[cpb.CONTINUITY], cpb.ATTACHED)
        self.assertEqual(states[cpb.DECLARATION], cpb.NOT_ASKED)
        self.assertEqual(self._assessment().missing, [])
        page = self._page()
        self.assertIn("F2: a currently certified parcel skips to section G", page)
        self.assertIn("parcels/certificates/", page)
        self.assertIn("parcels/continuity/", page)
        self.assertIn("form does not ask for the date-of-last-prohibited-material declaration here", page)
        self.assertNotIn("the operator has made no declaration", page)
        self.assertNotIn("is not covered", page, "the 36-month accounting is not this route's demand")
        for banned in ("verified", "eligible", "Eligible", "36 months accounted"):
            self.assertNotIn(banned, page)

    def test_a_missing_certificate_is_named_missing(self):
        self._upload(cpb.CONTINUITY_SECTION, "ccof-letter")
        self.assertEqual(self._states()[cpb.CERTIFICATE], cpb.MISSING)
        self.assertEqual(self._assessment().missing, [cpb.CERTIFICATE])
        self.assertIn("certified_certificate", parcel_evidence_status(self.parcel)["missing"])
        self.assertIn(
            "Copy of the current organic certificate listing this parcel: none attached or referenced", self._page()
        )

    def test_missing_continuity_evidence_is_not_filled_by_the_checkbox(self):
        self._upload(cpb.CERTIFICATE_SECTION, "certificate")
        states = self._states()
        self.assertEqual(states[cpb.CONTINUITY], cpb.MISSING)
        self.assertEqual(states[cpb.NO_LAPSE_STATEMENT], cpb.STATED_YES)
        page = self._page()
        self.assertIn("Verification of no lapse in organic management: none attached or referenced", page)
        self.assertIn("it is not the verification listed above", page)

    def test_a_reference_is_referenced_separately_never_attached(self):
        self._answer(
            certificate_reference="Certificate on file with CCOF under client 1234.",
            continuity_reference="CCOF continuity letter, 2026-03-02, kept in the farm office binder.",
        )
        states = self._states()
        self.assertEqual(states[cpb.CERTIFICATE], cpb.REFERENCED)
        self.assertEqual(states[cpb.CONTINUITY], cpb.REFERENCED)
        self.assertIn("referenced separately by the operator: CCOF continuity letter", self._page())

    def test_a_signed_land_history_affidavit_counts_as_continuity_evidence(self):
        LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="Self",
            management_period_start=self.today - relativedelta(years=4),
            signed_document=ContentFile(b"%PDF-1.4 affidavit", name="aff.pdf"),
        )
        self.assertEqual(self._states()[cpb.CONTINUITY], cpb.ATTACHED)

    def test_conflicting_records_stay_as_review_items(self):
        season = Production.objects.create(
            name="2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Grapes"),
            start_date=timezone.now() - timedelta(days=60),
        )
        ChemicalEvent.objects.create(
            history=season,
            date=timezone.now() - timedelta(days=30),
            description="spray",
            commercial_name="Synthetic X",
            organic_approved="not_organic",
        )
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=self.today.year - 1, crop_grown="Grapes", production_method="conventional"
        )
        review = " ".join(r.text for r in self._assessment().review)
        self.assertIn("Synthetic X", review)
        self.assertIn("inside a period stated as certified", review)
        self.assertIn("records conventional production", review)
        self.assertIn("[REVIEW]", self._page())

    def test_the_wizard_payload_and_the_page_carry_the_same_assessment(self):
        self._upload(cpb.CERTIFICATE_SECTION, "certificate")
        payload = land_history_summary(self.parcel)["certified_branch"]
        assessment = self._assessment()
        self.assertEqual(payload["route"], assessment.route)
        self.assertEqual(
            [(i["key"], i["state"], i["path"]) for i in payload["items"]],
            [(i.key, i.state, i.path) for i in assessment.items],
        )
        self.assertEqual([r["kind"] for r in payload["review"]], [r.kind for r in assessment.review])
        page = self._page()
        for item in assessment.items:
            self.assertIn(item.text[:60], page)


class CertifiedBranchInThePacketTests(_Certified):
    def test_the_certificate_copy_ships_where_the_page_says(self):
        import zipfile

        from certifications.services.osp_module_pdf import generate_osp_packet

        self._upload(cpb.CERTIFICATE_SECTION, "certificate")
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        shipped = [n for n in packet.namelist() if n.startswith("parcels/certificates/")]
        self.assertEqual(len(shipped), 1, packet.namelist())
        page_name = next(n for n in packet.namelist() if n.startswith("parcels/parcel-application-"))
        self.assertIn(shipped[0], _text(packet.read(page_name)))


class UncertifiedBranchTests(_Certified):
    def test_an_uncertified_parcel_keeps_the_36_month_accounting(self):
        self._answer(currently_certified="no")
        self.assertIsNone(self._assessment())
        self.assertIsNone(land_history_summary(self.parcel)["certified_branch"])
        page = self._page()
        self.assertIn("the operator has made no declaration", page)
        self.assertNotIn("skips to section G", page)


class WsdaBranchTests(_Certified):
    agent = "wsda"

    def test_an_existing_site_of_this_operation_asks_for_no_2264_land_history(self):
        assessment = self._assessment()
        self.assertEqual(assessment.route, "wsda_existing_site")
        self.assertEqual(assessment.missing, [])
        self.assertFalse(assessment.land_history_asked)
        self.assertIn("Organic Site Update (AGR 2516)", self._page())

    def test_a_transferred_site_asks_for_the_previous_growers_certificate_and_2262(self):
        self._answer(certified_operation_name="Valley Orchards Inc")
        assessment = self._assessment()
        self.assertEqual(assessment.route, "wsda_transfer")
        self.assertEqual(sorted(assessment.missing), [cpb.CERTIFICATE, cpb.PRIOR_MANAGER])
        page = self._page()
        self.assertIn("previous grower's certificate", page)
        self.assertIn("Previous Land Use Declaration (AGR 2262)", page)


class OtcoBranchTests(_Certified):
    agent = "otco"

    def test_existing_site_is_not_refiled_on_c2(self):
        self.assertEqual(self._assessment().route, "otco_existing_site")
        self.assertIn("FACT-04", self._page())

    def test_a_parcel_from_another_operation_still_needs_2_5_affirmations(self):
        self._answer(certified_operation_name="Hillside Berries")
        assessment = self._assessment()
        self.assertEqual(assessment.route, "otco_transfer")
        self.assertTrue(assessment.land_history_asked)
        self.assertEqual(assessment.missing, [cpb.PRIOR_MANAGER])
        page = self._page()
        self.assertIn("Land Transfer Form", page)
        # The accounting IS asked on this route, and it must not demand the declaration the form skips.
        self.assertIn("the declaration is not asked of a parcel stated currently certified", page)
        self.assertNotIn("the operator has made no declaration", page)


class UnregisteredAgentTests(_Certified):
    agent = "oci"

    def test_an_agent_without_a_register_is_told_its_own_form_decides(self):
        assessment = cpb.assess(self.parcel, None)
        self.assertEqual(assessment.route, "agent_form")
        self.assertEqual(
            assessment.missing, [], "Trazo claims no requirement for an agent whose form it does not carry"
        )
        page = self._page()
        # Run 3, R3-06: no exemption claimed for a form Trazo does not read; the accounting prints.
        self.assertIn("no agent-specific exemption is determined", page)
        self.assertIn("Whether the certifying agent asks for it is not determined", page)
        self.assertNotIn(cpb.COVERAGE_NOT_ASKED_TEXT[:60], page)
        self.assertNotIn("skips to section G", page)


class ReviewOfBack86Tests(_Certified):
    """Defects the review of back #86 found."""

    def _affidavit(self, name, start, end=None, signed=True):
        return LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name=name,
            management_period_start=start,
            management_period_end=end,
            signed_document=ContentFile(b"%PDF-1.4 affidavit", name=f"{name}.pdf") if signed else None,
        )

    def test_an_affidavit_whose_period_misses_the_window_is_not_continuity_evidence(self):
        self._affidavit("Old Owner", self.today - relativedelta(years=12), self.today - relativedelta(years=9))
        item = next(i for i in self._assessment().items if i.key == cpb.CONTINUITY)
        self.assertEqual(item.state, cpb.MISSING)
        self.assertIn("does not cover", item.text)

    def test_every_prior_party_must_have_signed(self):
        self._answer(certified_operation_name="Hillside Berries")
        self.agent = "otco"
        self._affidavit("Signed Party", self.today - relativedelta(years=5), self.today - relativedelta(years=2))
        self._affidavit("Unsigned Party", self.today - relativedelta(years=2), self.today, signed=False)
        item = next(i for i in self._assessment().items if i.key == cpb.PRIOR_MANAGER)
        self.assertEqual(item.state, cpb.MISSING)
        self.assertIn("1 of 2 signed", item.text)
        self.assertIn("Unsigned Party", item.text)

    def test_formatting_matches_this_operation_but_a_different_legal_entity_does_not(self):
        self._answer(certified_operation_name="Branch Farms, L.L.C.")
        self.assertEqual(cpb.branch_for(self.parcel), cpb.EXISTING_SITE)
        self._answer(certified_operation_name="Branch Farms Inc")
        self.assertEqual(cpb.branch_for(self.parcel), cpb.FROM_OTHER_OPERATION)
        kinds = [r.kind for r in self._assessment().review]
        self.assertIn("operation_name_not_on_file", kinds)

    def test_the_wizard_says_which_plan_it_assessed_and_a_packet_follows_its_own_plan(self):
        OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", certifier_name=AGENT_NAMES["wsda"]
        )
        payload = land_history_summary(self.parcel)["certified_branch"]
        # The parcel names Oregon Tilth as its certifier, so for WSDA it is a new site (run 3).
        self.assertEqual((payload["plan_version"], payload["route"]), (2, "wsda_new_site"))
        self.assertIn("skips to section G", self._page(), "the v1 packet speaks for v1's agent")

    def test_files_off_the_route_do_not_ship(self):
        import zipfile

        from certifications.services.osp_module_pdf import generate_osp_packet

        self._upload(cpb.CERTIFICATE_SECTION, "certificate")
        self._answer(currently_certified="no")
        names = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).namelist()
        self.assertFalse([n for n in names if n.startswith("parcels/certificates/")], names)

    def test_the_wizard_coverage_says_not_asked_on_a_route_that_does_not_ask(self):
        coverage = land_history_summary(self.parcel)["coverage"]
        self.assertTrue(coverage["not_asked"])
        self.assertEqual(coverage["gaps"], [])
        self.assertIsNone(coverage["complete"])
        self.assertEqual(coverage["text"], cpb.COVERAGE_NOT_ASKED_TEXT)
        self.assertIn(cpb.COVERAGE_NOT_ASKED_TEXT[:60], self._page())


class ReviewOfBack86TransferTests(_Certified):
    agent = "otco"

    def test_otco_transfer_ships_no_certificate_and_keeps_the_accounting(self):
        import zipfile

        from certifications.services.osp_module_pdf import generate_osp_packet

        self._answer(certified_operation_name="Hillside Berries")
        self._upload(cpb.CERTIFICATE_SECTION, "certificate")
        names = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))).namelist()
        self.assertFalse([n for n in names if n.startswith("parcels/certificates/")], "C2 2.5 lists no certificate")
        self.assertFalse(land_history_summary(self.parcel)["coverage"]["not_asked"])


# ---------------------------------------------------------------------------------------------------
# Run 3 (2026-10-02): one applicability decision per parcel and form, for the packet's own plan.
# One applicability decision per parcel and form, for the packet's own plan (run 3, R3-04/05/06).
#
# WHY THIS EXISTS
# ---------------
# Astra's run-3 review of the 2026-10-01 handoff found three renderers deciding a certified parcel's
# route on their own:
#
# * R3-05: the parcel summary counted one missing item while its own route page named three. The
#   summary read the newest plan in the database; the page read the packet's plan.
# * R3-04: page 04 listed OTCO C2 2.4 and WSDA AGR 2264 6a/8/14 as "still open" for parcels whose
#   route pages said those forms are not filed for them.
# * R3-06: OCI and MOSA parcel pages deferred to the agent's own form, then claimed that form "does not
#   ask for the 36-month accounting".
#
# And one rule Oscar added on approval: "currently certified" does not by itself mean existing acreage
# under the selected agent. The agent named for the parcel must be the selected agent; an unknown or
# missing name leaves the route unresolved, never skipped.
#
# Every test here builds a packet surface and compares it with the same assessment, so a renderer that
# decides on its own fails.
# ---------------------------------------------------------------------------------------------------

#: The demo farm's fictional certifier: a name Trazo does not recognise.
UNRECOGNISED = "Cascadia Organic Certifiers"

PARCEL_FORM = {"ccof": "ORGB49", "wsda": "AGR 2264", "otco": "C2"}


class _Packet(TestCase):
    def setUp(self):
        today = timezone.now().date()
        self.company = Company.objects.create(name="Branch Farms LLC")
        self.est = Establishment.objects.create(name="Branch Farm", company=self.company, state="OR")
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="CERT-1",
            certifier_name=AGENT_NAMES["otco"],
            usda_operation_name="Branch Farms LLC",
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=AGENT_NAMES["ccof"]
        )
        self.parcel = Parcel.objects.create(
            name="North Block",
            establishment=self.est,
            area=4.0,
            date_began_managing=today - relativedelta(years=8),
            application_answers={"currently_certified": "yes", "no_lapse_attested": True},
        )

    def _set(self, agent=None, named=None, operation=None, osp=None):
        osp = osp or self.osp
        if agent is not None:
            osp.certifier_name = AGENT_NAMES[agent]
            osp.save(update_fields=["certifier_name"])
        answers = dict(self.parcel.application_answers)
        answers["prior_certifier_name"] = AGENT_NAMES.get(named, named) if named else ""
        if operation is not None:
            answers["certified_operation_name"] = operation
        self.parcel.application_answers = answers
        self.parcel.save(update_fields=["application_answers"])

    def _route(self, osp=None):
        return cpb.assess_for_plan(self.parcel, osp or self.osp)

    def _page(self, osp=None):
        return _text(generate_module_pdf(osp or self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))

    def _form(self, agent, osp=None):
        forms = form_coverage(osp or self.osp, agent)
        return next(f for f in forms if f.document_id == PARCEL_FORM[agent])

    def _summary_count(self, page):
        match = re.search(r"Supporting evidence: (\d+) items? outstanding \(([^)]*)\)", page)
        return (int(match.group(1)), match.group(2)) if match else (0, "")


class RouteFollowsTheSelectedAgentTests(_Packet):
    """Rule 1: the selected agent and the agent named for the parcel decide the route together."""

    def test_ccof_parcel_already_on_ccof_file_is_a_crop_update_not_nopb49(self):
        self._set(agent="ccof", named="ccof")
        route = self._route()
        self.assertEqual(route.route, "ccof_crop_update")
        page = self._page()
        # A resolved route keeps "not asked" and carries no undetermined note (run 4, R4-01).
        self.assertIn("Not asked by this certifying agent's form", page)
        self.assertNotIn("not determined", page)
        self.assertIs(route.land_history_asked, False)
        self.assertEqual(route.missing, [])
        self.assertIn("Crop Update (ORGB88)", self._page())

    def test_ccof_parcel_certified_by_another_agent_takes_f2_to_g(self):
        self._set(agent="ccof", named="otco")
        self.assertEqual(self._route().route, "ccof_g")

    def test_wsda_existing_site_needs_wsda_named(self):
        self._set(agent="wsda", named="wsda")
        self.assertEqual(self._route().route, "wsda_existing_site")
        self._set(named="otco")
        route = self._route()
        self.assertEqual(route.route, "wsda_new_site", "certified by another agent is new to WSDA")
        self.assertIs(route.land_history_asked, True)

    def test_wsda_transfer_is_between_wsda_operations(self):
        self._set(agent="wsda", named="wsda", operation="Valley Orchards Inc")
        self.assertEqual(self._route().route, "wsda_transfer")
        self._set(named="otco")
        route = self._route()
        self.assertEqual(route.route, "wsda_new_site")
        # Another operation's land still needs its previous manager's AGR 2262 (review of back #90).
        self.assertIn(cpb.PRIOR_MANAGER, route.missing)
        self.assertIn("Previous Land Use Declaration (AGR 2262)", self._page())

    def test_wsda_new_site_on_this_operations_land_asks_no_prior_manager(self):
        self._set(agent="wsda", named="otco")
        self.assertNotIn(cpb.PRIOR_MANAGER, [i.key for i in self._route().items])

    def test_otco_existing_acreage_needs_otco_named(self):
        self._set(agent="otco", named="otco")
        self.assertEqual(self._route().route, "otco_existing_site")
        self._set(named="wsda")
        route = self._route()
        self.assertEqual(route.route, "otco_new_acreage")
        self.assertIs(route.land_history_asked, True)
        alternatives = {i.key for i in route.items if i.alternative}
        self.assertEqual(alternatives, {cpb.CERTIFICATE, cpb.CONTINUITY})
        self.assertEqual(route.missing, [], "an alternative C2 2.4 accepts is never counted as outstanding")

    def test_an_unknown_or_missing_agent_name_leaves_every_routed_agent_unresolved(self):
        for agent in ("ccof", "wsda", "otco"):
            for named in (UNRECOGNISED, None):
                with self.subTest(agent=agent, named=named):
                    self._set(agent=agent, named=named)
                    route = self._route()
                    self.assertEqual(route.route, "unresolved")
                    self.assertIsNone(route.land_history_asked, "undetermined, never 'not asked'")
                    self.assertIn("certifier_not_recognised", [r.kind for r in route.review])
                    page = self._page()
                    self.assertNotIn(cpb.COVERAGE_NOT_ASKED_TEXT[:60], page)
                    self.assertIn("Window ", page, "the accounting prints in full")
                    # Run 4, R4-01: no item reads "not asked" when applicability is undetermined, and
                    # the summary says the evidence count is not the full set.
                    self.assertNotIn("Not asked by this certifying agent's form", page)
                    self.assertIn("Whether this certifying agent asks for this is not determined", page)
                    self.assertIn("evidence this agent asks for is not determined", page)
                    if named:
                        self.assertIn(UNRECOGNISED, page)


class FallbackAgentsClaimNoExemptionTests(_Packet):
    """R3-06, for both agents whose forms Trazo does not read (rule 5)."""

    def test_oci_and_mosa_defer_without_an_exemption(self):
        for agent in ("oci", "mosa"):
            with self.subTest(agent=agent):
                self._set(agent=agent, named=agent)
                route = self._route()
                self.assertEqual(route.route, "agent_form")
                self.assertIsNone(route.land_history_asked)
                self.assertEqual(route.missing, [])
                page = self._page()
                self.assertIn("no agent-specific exemption is determined", page)
                self.assertNotIn("does not ask for the 36-month accounting", page)
                self.assertNotIn(cpb.COVERAGE_NOT_ASKED_TEXT[:60], page)
                self.assertIn("Window ", page)
                # Run 4, R4-01: every item, both fallback agents.
                self.assertNotIn("Not asked by this certifying agent's form", page)
                self.assertEqual(page.count("Whether this certifying agent asks for this is not determined"), 2)
                self.assertIn("this agent's own form sets the evidence it asks for", page.lower())


class SummaryAgreesWithTheRouteTests(_Packet):
    """R3-05: the summary line counts the route's own missing items, in words."""

    def _assert_agrees(self, osp):
        route = self._route(osp)
        status = parcel_application_status(self.parcel, osp=osp)
        certified_missing = [k for k in status["evidence_missing"] if k.startswith("certified_")]
        self.assertEqual(certified_missing, [f"certified_{k}" for k in route.missing])
        page = self._page(osp)
        count, labels = self._summary_count(page)
        self.assertEqual(count, len(status["evidence_missing"]), page[:400])
        self.assertNotIn("certified_", labels, "no internal key prints")
        return route, labels

    def test_ccof_g_counts_both_missing_items_in_words(self):
        self._set(agent="ccof", named="otco")
        route, labels = self._assert_agrees(self.osp)
        self.assertEqual(sorted(route.missing), [cpb.CERTIFICATE, cpb.CONTINUITY])
        self.assertIn("no copy of the certificate attached or referenced", labels)
        self.assertIn("no verification of no lapse attached or referenced", labels)

    def test_active_and_draft_plans_each_count_their_own_route(self):
        self._set(agent="ccof", named="otco")
        draft = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", certifier_name=AGENT_NAMES["wsda"]
        )
        active_route, _ = self._assert_agrees(self.osp)
        draft_route, _ = self._assert_agrees(draft)
        self.assertEqual((active_route.route, draft_route.route), ("ccof_g", "wsda_new_site"))
        # The wizard still names the plan it assessed: the newest one.
        self.assertEqual(cpb.assess_for_wizard(self.parcel).plan_version, 2)

    def test_an_agent_chosen_on_the_plan_without_saving_reaches_every_surface(self):
        self._set(agent="ccof", named="otco")
        self.osp.certifier_name = AGENT_NAMES["wsda"]  # in memory only
        route, _ = self._assert_agrees(self.osp)
        self.assertEqual(route.route, "wsda_new_site")
        self.assertIn("for WSDA it is a new site", self._page(self.osp))
        self.assertEqual(self._form("wsda").standing, "in_part")
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.certifier_name, AGENT_NAMES["ccof"], "nothing persisted")


class CoveragePageFollowsEachParcelsRouteTests(_Packet):
    """R3-04: page 04 lists a row the route skips apart from open rows, and never as answered."""

    def test_forms_not_filed_on_the_existing_site_route(self):
        for agent, reason in (
            ("wsda", "AGR 2264 is not filed for an existing certified site"),
            ("otco", "C2 is not refiled for currently certified acreage"),
            ("ccof", "a parcel already on the operation's CCOF file changes on the Crop Update"),
        ):
            with self.subTest(agent=agent):
                self._set(agent=agent, named=agent)
                form = self._form(agent)
                self.assertEqual(form.standing, "not_on_route")
                self.assertEqual(form.open_rows, ())
                page = _text(_coverage_pdf(self.osp))
                self.assertIn("Forms not filed for these parcels on their route", page)
                self.assertIn(reason, page)

    def test_ccof_g_skips_f3_to_f8_and_keeps_the_rest_open(self):
        self._set(agent="ccof", named="otco")
        form = self._form("ccof")
        skipped = {row.ref for row in form.route_skipped_rows}
        self.assertTrue(skipped <= {"F3", "F4", "F5", "F6", "F7", "F7a", "F8", "F8a"}, skipped)
        self.assertTrue({"F4", "F6"} <= skipped, skipped)
        self.assertFalse(skipped & {row.ref for row in form.open_rows})
        self.assertNotEqual(form.standing, "answered")
        self.assertIn("F2 Yes: a currently certified parcel skips to section G", _text(_coverage_pdf(self.osp)))

    def test_routes_that_file_the_form_skip_nothing(self):
        for agent, named, operation in (
            ("wsda", "otco", None),
            ("wsda", "wsda", "Valley Orchards Inc"),
            ("otco", "wsda", None),
            ("otco", "otco", "Hillside Berries"),
        ):
            with self.subTest(agent=agent, named=named, operation=operation):
                self._set(agent=agent, named=named, operation=operation or "")
                form = self._form(agent)
                self.assertEqual(form.route_skipped_rows, ())
                self.assertNotEqual(form.standing, "not_on_route")

    def test_an_unresolved_route_is_open_with_its_reason_never_skipped(self):
        for agent in ("wsda", "otco", "ccof"):
            with self.subTest(agent=agent):
                self._set(agent=agent, named=UNRECOGNISED)
                form = self._form(agent)
                self.assertEqual(form.route_skipped_rows, ())
                states = {row.state for row in form.open_rows}
                self.assertIn("route_unresolved", states)
                # Recordkeeping review S9 (F-15): one clause per form naming the parcels and the answer to fix.
                self.assertIn(
                    "not determined for North Block: name each parcel's prior certifying agent",
                    _text(_coverage_pdf(self.osp)),
                )

    def test_one_parcel_on_route_keeps_the_row_open_for_that_parcel(self):
        self._set(agent="otco", named="otco")
        Parcel.objects.create(
            name="New Ground",
            establishment=self.est,
            area=2.0,
            date_began_managing=timezone.now().date() - relativedelta(years=1),
            application_answers={"currently_certified": "no"},
        )
        form = self._form("otco")
        self.assertNotEqual(form.standing, "not_on_route", "C2 is filed for the uncertified parcel")
        self.assertEqual(form.route_skipped_rows, ())
