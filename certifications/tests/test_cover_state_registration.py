"""The renewal packet cover prints a California operation's CDFA organic registration.

CCOF Certification Contract E1 and OTCO O1 E-1 both ask for it. The number was recorded on
`StateOrganicRegistration` and printed in the audit dossier only, so neither agent's form could be
copied from the packet.
"""

from datetime import date, timedelta

from django.test import TestCase

from certifications.models import OrganicSystemPlan, StateOrganicRegistration
from certifications.services.osp_module_pdf import _packet_cover_pdf
from company.models import Company, Establishment

from .test_renewal_packet_contents import _pdf_text

LABEL = "California organic registration (CDFA):"


class CoverStateRegistrationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Valley Walnuts LLC")
        self.est = Establishment.objects.create(name="Valley Walnuts", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name="CCOF"
        )

    def _cover(self):
        return _pdf_text(_packet_cover_pdf(self.osp))

    def _register(self, **kw):
        fields = dict(
            establishment=self.est,
            state="CA",
            status="registered",
            registration_number="12-123456",
            county="Butte",
            registration_date=date.today() - timedelta(days=30),
            renewal_date=date.today() + timedelta(days=300),
        )
        fields.update(kw)
        return StateOrganicRegistration.objects.create(**fields)

    def test_a_current_registration_prints_its_number_county_and_renewal(self):
        reg = self._register()
        text = self._cover()
        self.assertIn(
            f"{LABEL} 12-123456 (Registered, Butte County, renewal date {reg.renewal_date.isoformat()})", text
        )
        self.assertNotIn("[REVIEW]", text.split(LABEL, 1)[1].split("Plan submitted", 1)[0])

    def test_the_newest_registration_is_the_one_printed(self):
        self._register(registration_number="12-000001", registration_date=date.today() - timedelta(days=400))
        self._register(registration_number="12-000002")
        text = self._cover()
        self.assertIn(f"{LABEL} 12-000002", text)
        self.assertNotIn("12-000001", text)

    def test_a_lapsed_registration_is_printed_with_a_review_line(self):
        self._register(
            renewal_date=date.today() - timedelta(days=1), registration_date=date.today() - timedelta(days=400)
        )
        text = self._cover()
        self.assertIn(f"{LABEL} 12-123456", text)
        self.assertIn("[REVIEW] The registration's renewal date", text)
        self.assertIn("has passed.", text)

    def test_a_registration_without_a_number_says_so(self):
        self._register(registration_number="")
        text = self._cover()
        self.assertIn(f"{LABEL} number not recorded", text)
        self.assertIn("[REVIEW] The registration number is not recorded", text)

    def test_an_exempt_operation_without_a_number_is_told_it_must_still_register(self):
        self._register(status="exempt", registration_number="")
        text = self._cover()
        self.assertIn(f"{LABEL} number not recorded", text)
        self.assertIn("exempt from certification only; California still requires it to register", text)

    def test_an_exempt_operation_with_its_number_prints_without_a_review(self):
        self._register(status="exempt")
        text = self._cover()
        self.assertIn(f"{LABEL} 12-123456 (Registered, exempt from certification", text)
        self.assertNotIn("[REVIEW]", text.split(LABEL, 1)[1].split("Plan submitted", 1)[0])

    def test_a_california_operation_with_none_on_file_is_told_where_to_add_it(self):
        text = self._cover()
        self.assertIn(f"{LABEL} none on file", text)
        self.assertIn("[REVIEW] CCOF's and Oregon Tilth's forms ask a California operation", text)

    def test_an_operation_elsewhere_with_none_on_file_gets_no_line(self):
        self.est.state = "WA"
        self.est.save(update_fields=["state"])
        self.assertNotIn("CDFA", self._cover())

    def test_the_state_is_read_in_any_spelling_the_profile_holds(self):
        self.est.state = "California"
        self.est.save(update_fields=["state"])
        self.assertIn(f"{LABEL} none on file", self._cover())
