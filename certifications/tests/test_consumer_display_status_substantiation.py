"""The consumer "Verified via USDA Organic Integrity Database" claim needs a source.

`consumer_display_status == "verified_via_database"` renders that literal sentence on the
public QR page. It used to be derived from `verification_status == "verified"` alone, so any
row marked verified without an actual OID match — a manual admin edit, a data import, a
fixture — asserted a third-party database verification that never happened. That is the
substantiation problem FTC 16 CFR 260.6 is about, on the strongest claim the page makes.

The claim is now gated on `verification_source`; everything else degrades to the honest
`self_reported` label rather than silently upgrading a farmer attestation.
"""

import datetime

from django.test import TestCase

from certifications.models import Certification
from company.models import Company, Establishment


class ConsumerDisplayStatusSubstantiationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Dry Creek Groves LLC")
        cls.establishment = Establishment.objects.create(company=company, name="Dry Creek Home Ranch")

    def _cert(self, **overrides):
        kwargs = {
            "establishment": self.establishment,
            "certification_type": "usda_organic",
            "certification_number": "CCOF-2019-14882",
            "certifier_name": "CCOF Certification Services, LLC",
            "expiry_date": datetime.date.today() + datetime.timedelta(days=365),
        }
        kwargs.update(overrides)
        return Certification(**kwargs)

    def test_database_match_keeps_the_verified_claim(self):
        """A real OID match is exactly what the sentence claims — it must survive."""
        cert = self._cert(
            verification_status="verified",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )
        self.assertEqual(cert.consumer_display_status, "verified_via_database")

    def test_verified_without_a_source_does_not_claim_a_database_match(self):
        """The shape found in live data: verified, but nothing substantiating it."""
        cert = self._cert(verification_status="verified", verification_source=None)
        self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_verified_from_another_source_does_not_claim_a_database_match(self):
        """A directory listing or a seed script is not the Integrity Database."""
        for source in ("real_organic_project_directory", "manual_qa_seed", ""):
            with self.subTest(source=source):
                cert = self._cert(verification_status="verified", verification_source=source)
                self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_self_reported_is_unchanged(self):
        cert = self._cert(verification_status="self_reported", verification_source=None)
        self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_revoked_is_still_inactive_even_with_a_database_source(self):
        """A revoked cert must not be rescued by its source."""
        cert = self._cert(
            verification_status="revoked",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )
        self.assertEqual(cert.consumer_display_status, "inactive")

    def test_pending_is_unchanged(self):
        cert = self._cert(
            verification_status="pending",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )
        self.assertEqual(cert.consumer_display_status, "pending")

    def test_constant_matches_the_verifier_that_stamps_it(self):
        """If the verifier's identifier drifts, every real badge silently downgrades."""
        from certifications.services.usda_organic_verifier import USDAOrganicVerifier

        self.assertEqual(
            USDAOrganicVerifier().source_identifier,
            Certification.DATABASE_VERIFICATION_SOURCE,
        )
