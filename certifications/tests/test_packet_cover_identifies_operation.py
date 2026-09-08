"""The renewal packet cover must name the operation the way § 205.401(b) asks.

WHY THIS EXISTS
---------------
Found 2026-09-07 by walking a new WSDA orchard through signup, company setup, farm creation,
one OSP module, submit, activate and a renewal fork — then reading the packet it produced.

Two lines of the cover were wrong at once, and both were wrong on the document the certifying
agent reads:

1. **The certificate never printed.** `OSPViewSet.activate` is the strictest gate in the
   product — it REQUIRES an approval document, a certificate number and a certifying agent's
   name before a plan may go active, and writes all three to the OSP. The cover read
   `Certification` rows instead: the farm profile's certification list, which nothing in the
   OSP flow asks a grower to fill. A farm that had just satisfied that gate printed
   "Certificate: —" and named no certifier anywhere in the packet.

2. **The responsible person contradicted itself.** With no contact person on the farm profile
   the cover falls back to the plan's author — correct, a name a reviewer can call beats a
   dash — but then printed, one line below, "The operation has no contact person on its farm
   profile." Two adjacent lines asserting opposite things.
"""

from django.test import TestCase

from certifications.models import Certification, OrganicSystemPlan
from certifications.services.osp_module_pdf import _packet_cover_pdf
from company.models import Company, Establishment
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text


class _CoverFarm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Cascade Ridge Orchards LLC")
        self.user = User.objects.create_user(
            email="cover@test.com", password="x", first_name="Dale", last_name="Brennan"
        )
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Squilchuck Home Ranch", company=self.company)


class CertificateFromTheActivationGateTests(_CoverFarm):
    """The number the grower typed to activate is the number the cover prints."""

    def _activated_v1(self):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            approval_certificate_number="WA-ORG-2026-4471",
            approval_certifier_name="Washington State Department of Agriculture",
        )

    def test_certificate_number_prints_on_the_cover(self):
        osp = self._activated_v1()
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("WA-ORG-2026-4471", text)

    def test_certifying_agent_is_named(self):
        osp = self._activated_v1()
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("Washington State Department of Agriculture", text)

    def test_a_renewal_draft_names_the_certificate_that_approved_the_prior_version(self):
        """v2 is a draft; the certificate the operation HOLDS is the one that approved v1."""
        self._activated_v1()
        v2 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="draft")
        text = _pdf_text(_packet_cover_pdf(v2))
        self.assertIn("WA-ORG-2026-4471", text)

    def test_an_operation_with_no_approval_anywhere_still_prints_a_dash(self):
        """Absence must read as absence — never as a blank the reviewer has to interpret."""
        osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("Certificate", text)
        self.assertNotIn("WA-ORG", text)


class TheCertificateAndItsAgentComeFromOneRecordTests(_CoverFarm):
    """🔴 Found 2026-09-07 re-reading the fix above with fresh eyes.

    The first version filled the number and the agent independently, each from whichever source
    had it. An operation with a farm-profile certificate row carrying a number but no agent, plus
    a WSDA-approved plan, printed a CCOF certificate number beside the WSDA name — a number
    attributed to an agent that did not issue it, on the document that agent reads. Worse than the
    blank it replaced.
    """

    def test_a_number_is_never_printed_beside_another_records_agent(self):
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="CCOF-2026-1234",
            certifier_name="",
        )
        OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            approval_certificate_number="WA-ORG-2026-4471",
            approval_certifier_name="Washington State Department of Agriculture",
        )
        text = _pdf_text(_packet_cover_pdf(OrganicSystemPlan.objects.get(establishment=self.est)))
        self.assertNotIn(
            "CCOF-2026-1234 — Washington State Department of Agriculture",
            text,
            "the cover paired one record's certificate number with another record's agent",
        )
        self.assertIn("CCOF-2026-1234", text)

    def test_an_expired_certificate_does_not_supply_the_agent(self):
        """Sorting by effective date alone let a revoked or expired row win. The demo operation
        had exactly this shape: an inactive row naming CCOF with a later effective date than the
        active one naming its real agent."""
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="OLD-9999",
            certifier_name="CCOF",
            effective_date="2026-08-27",
            expiry_date="2026-08-28",
        )
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="COC-1463",
            certifier_name="Cascadia Organic Certifiers",
            effective_date="2026-05-15",
        )
        osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("COC-1463 — Cascadia Organic Certifiers", text)
        self.assertNotIn("OLD-9999", text)


class ResponsiblePersonDoesNotContradictItselfTests(_CoverFarm):
    def test_the_fallback_name_is_labelled_as_a_fallback(self):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("Dale Brennan", text)
        self.assertIn("plan author", text)

    def test_the_cover_never_says_there_is_no_name_while_printing_one(self):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("Dale Brennan", text)
        self.assertNotIn("has no contact person", text)

    def test_a_named_contact_person_carries_no_fallback_note(self):
        self.est.contact_person = "Dale Brennan"
        self.est.save(update_fields=["contact_person"])
        osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        text = _pdf_text(_packet_cover_pdf(osp))
        self.assertIn("Dale Brennan", text)
        self.assertNotIn("plan author", text)
