"""A currently certified parcel follows its certifier's own branch (OSP alignment audit T21-F1).

WHY THIS EXISTS
---------------
The Calapooia specimen showed a certified parcel's page printing "the operation's own period ...
is not covered: the operator has made no declaration", while the same page said the declaration is
not asked of a certified parcel. The page demanded a statement the form skips.

The fix follows each agent's route (CCOF NOPB49 F2 to G; WSDA AGR 2264 only for new sites and
transfers; OTCO C2 only for new applications and added acreage) and states, item by item, what is
attached, referenced separately or missing. It never manufactures the skipped declaration from
"currently certified", never counts the operator's no-lapse checkbox as verification, and never
says "verified" or "eligible". The wizard payload and the PDF print one assessment.
"""

import io
from datetime import timedelta

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from pdfminer.high_level import extract_text

from certifications.models import Certification, LandownerAffidavit, OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services import certified_parcel_branch as cpb
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.parcel_land_history import land_history_summary
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import ChemicalEvent, History
from product.models import Parcel, ParcelCropHistory, Product
from product.services.parcel_application_status import parcel_evidence_status

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
                "prior_certifier_name": AGENT_NAMES[self.agent],
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
        self.assertIn("declaration is not asked on this branch", page)
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
        season = History.objects.create(
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
        self.assertIn("does not carry the certifying agent's own parcel form", page)
        self.assertIn("whether the certifying agent asks it is set by its own form", page)
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
        self.assertEqual((payload["plan_version"], payload["route"]), (2, "wsda_existing_site"))
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
