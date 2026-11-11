"""A packet for an operation that has never been certified does not demand an annual update.

Found by the overall review of 2026-11 (OV-PK-F01): the only real grower at the time was a
first-time applicant with no certificate, and his packet was titled "Organic System Plan,
Renewal Packet", told him on the cover that § 205.406(a) requires an annual update each year
and to "file it before this packet is sent", and said the same on document 02. A first
application is made under § 205.401; the annual update continues a certification that exists.

The test for "never certified" is deliberately wide, so these tests also hold the other side:
any record that says the operation was certified keeps the renewal reading, including a plan
approved without a certificate number typed in (several renewal fixtures look like that).
"""

import io
from datetime import date

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import Certification, OrganicSystemPlan
from certifications.services.operation_certificate import never_certified
from certifications.services.osp_module_pdf import _annual_update_pdf, _packet_cover_pdf, _renewal_status_pdf
from company.models import Company, Establishment
from users.models import User


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Operation(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="applicant@test.com", password="x", first_name="Dana")
        company = Company.objects.create(name="Walnut Applicant LLC")
        self.est = Establishment.objects.create(name="Walnut Bench", company=company, state="CA")
        self.plan = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            created_by=self.user,
            certifier_name="Organic Certifiers, Inc.",
        )


class NeverCertifiedReadingTests(_Operation):
    def test_a_draft_plan_with_no_certificate_reads_as_never_certified(self):
        self.assertTrue(never_certified(self.est.id))

    def test_any_nop_certificate_row_keeps_the_renewal_reading(self):
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certifier_name="Organic Certifiers, Inc.",
            effective_date=date(2020, 1, 1),
        )
        self.assertFalse(never_certified(self.est.id))

    def test_an_approved_plan_keeps_the_renewal_reading_even_without_a_number(self):
        self.plan.status = "active"
        self.plan.save(update_fields=["status"])
        self.assertFalse(never_certified(self.est.id))

    def test_an_approval_agent_on_any_version_keeps_the_renewal_reading(self):
        self.plan.approval_certifier_name = "Organic Certifiers, Inc."
        self.plan.save(update_fields=["approval_certifier_name"])
        self.assertFalse(never_certified(self.est.id))


class ApplicantPacketWordingTests(_Operation):
    def test_the_cover_neither_titles_a_renewal_nor_demands_an_update(self):
        text = _text(_packet_cover_pdf(self.plan))
        self.assertIn("Organic System Plan packet", text)
        self.assertIn("No certificate on file", text)
        self.assertIn("§ 205.401", text)
        self.assertNotIn("Renewal Packet", text)
        self.assertNotIn("file it before this packet is sent", text)
        self.assertIn("02. Annual update: none applies", text)

    def test_document_02_says_no_update_applies(self):
        text = _text(_annual_update_pdf(self.plan))
        self.assertIn("No annual update applies to this operation", text)
        self.assertNotIn("file it before the packet is sent", text)

    def test_02s_says_listed_forms_are_renewal_forms(self):
        text = _text(_renewal_status_pdf(self.plan))
        self.assertIn("a first application under § 205.401 uses the agent's application forms", text)


class RenewalPacketWordingUnchangedTests(_Operation):
    def setUp(self):
        super().setUp()
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="OCI-0042",
            certifier_name="Organic Certifiers, Inc.",
            effective_date=date(2020, 1, 1),
        )

    def test_a_certified_operation_still_gets_the_renewal_cover_and_the_demand(self):
        text = _text(_packet_cover_pdf(self.plan))
        self.assertIn("Renewal Packet", text)
        self.assertIn("Continuation of certification", text)
        self.assertIn("file it before this packet is sent", text)
        self.assertNotIn("No certificate on file", text)
        self.assertIn("No § 205.406(a) annual update is on file", _text(_annual_update_pdf(self.plan)))
