"""What the first run as a new WSDA grower found about naming the certifier and the certificate (2026-11-21).

A grower renewing with WSDA typed "WSDA (Washington State Department of Agriculture)" as each parcel's current
certifier. No name Trazo knows matched it exactly, so all three parcels fell out of WSDA's routing: the packet
printed "[REVIEW] The certifying agent named for this parcel ... is not one Trazo recognises" and a full-window
"[REVIEW] not accounted for" land-history line on land certified since 2017. She had also added her WSDA
certification to the farm profile without its number, and every parcel page said "No certificate is on file
for this operation in Trazo" while G8.0 counted one certificate on file.
"""

import io
from datetime import date

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.certifying_agents import agent_for_name
from certifications.models import Certification, OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services import certified_parcel_branch as cpb
from certifications.services.operation_certificate import recorded_without_number
from certifications.services.osp_module_pdf import _cover_certificate_value, generate_module_pdf
from certifications.services.parcel_land_history import land_history_summary
from company.models import Company, Establishment
from product.models import Parcel

PAIRED = "WSDA (Washington State Department of Agriculture)"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class PairedAgentNameTests(SimpleTestCase):
    def test_two_spellings_of_one_agent_name_it(self):
        self.assertIsNone(agent_for_name("WSDA Washington State Department of Agriculture"), "premise: no alias")
        for name in (
            PAIRED,
            "Washington State Department of Agriculture (WSDA)",
            "WSDA — Washington State Department of Agriculture",
            "WSDA - Washington State Department of Agriculture",
        ):
            agent = agent_for_name(name)
            self.assertIsNotNone(agent, name)
            self.assertEqual(agent.slug, "wsda", name)

    def test_two_agents_name_neither(self):
        self.assertEqual(agent_for_name("CCOF").slug, "ccof", "premise: each half is an agent")
        self.assertIsNone(agent_for_name("CCOF (Washington State Department of Agriculture)"))
        self.assertIsNone(agent_for_name("WSDA — Oregon Tilth Certified Organic"))

    def test_a_half_that_is_no_agent_names_none(self):
        self.assertIsNone(agent_for_name("WSDA (our county office)"))

    def test_hyphenated_names_are_not_split(self):
        self.assertEqual(agent_for_name("NOFA-NY Certified Organic, LLC").slug, "nofany")
        self.assertEqual(agent_for_name("Pro-Cert Organic Systems, Ltd.").slug, "procert")


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Sample Ridge Orchards")
        self.est = Establishment.objects.create(name="Sample Ridge", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            certifier_name="Washington State Department of Agriculture",
        )
        self.parcel = Parcel.objects.create(
            name="Block A",
            establishment=self.est,
            area=6.0,
            date_began_managing=date(2017, 1, 1),
            application_answers={"currently_certified": "yes", "prior_certifier_name": PAIRED},
        )

    def _parcel_text(self):
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))


class PairedNameRoutesTheParcelTests(_Farm):
    def test_the_parcel_takes_wsdas_existing_site_route(self):
        assessment = cpb.assess_for_plan(self.parcel, self.osp)
        self.assertIsNotNone(assessment)
        self.assertEqual(assessment.route, "wsda_existing_site")

    def test_the_window_is_not_demanded_of_a_site_already_on_the_certificate(self):
        summary = land_history_summary(self.parcel)
        self.assertTrue(summary["coverage"]["not_asked"])
        self.assertEqual(summary["coverage"]["gaps"], [])
        text = self._parcel_text()
        self.assertIn("Land history", text, "premise: section F printed")
        self.assertNotIn("not one Trazo recognises", text)
        self.assertNotIn("[REVIEW] not accounted for", text)


class CertificateWithoutNumberTests(_Farm):
    def _certify(self, number=""):
        return Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certifier_name="Washington State Department of Agriculture",
            certification_number=number,
            effective_date=date(2020, 1, 1),
        )

    def test_nothing_recorded_is_none(self):
        self.assertIsNone(recorded_without_number(self.est.id))
        self.assertIn("No certificate is on file for this operation in Trazo.", self._parcel_text())

    def test_a_certificate_without_its_number_is_named_not_denied(self):
        self._certify()
        self.assertEqual(recorded_without_number(self.est.id), "Washington State Department of Agriculture")
        text = self._parcel_text()
        self.assertIn("currently certified", text, "premise: the certified branch printed")
        self.assertNotIn("No certificate is on file", text)
        self.assertIn(
            "The farm profile records this operation's organic certificate from Washington State Department of "
            "Agriculture without its number",
            text,
        )
        summary = land_history_summary(self.parcel)
        self.assertIsNone(summary["certificate"])
        self.assertEqual(summary["certificate_unnumbered_agent"], "Washington State Department of Agriculture")

    def test_the_cover_line(self):
        self.assertEqual(
            _cover_certificate_value(
                {"certificate_number": "", "certifier_name": "", "certificate_unnumbered_agent": "WSDA"}
            ),
            "recorded on the farm profile, number not recorded — WSDA",
        )
        self.assertEqual(
            _cover_certificate_value(
                {"certificate_number": "", "certifier_name": "", "certificate_unnumbered_agent": None}
            ),
            "—",
        )
        self.assertEqual(
            _cover_certificate_value({"certificate_number": "1234", "certifier_name": "WSDA"}), "1234 — WSDA"
        )

    def test_a_numbered_certificate_is_the_certificate_of_record(self):
        self._certify(number="WSDA-4821")
        self.assertIsNone(recorded_without_number(self.est.id))
        summary = land_history_summary(self.parcel)
        self.assertEqual(summary["certificate"]["number"], "WSDA-4821")
        self.assertIsNone(summary["certificate_unnumbered_agent"])
