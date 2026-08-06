from datetime import date, timedelta

from django.test import TestCase

from company.models import Company, Establishment
from users.models import User

from ..models import Certification, CertificationVerificationLog


class CertificationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")
        self.company = Company.objects.create(name="Test Farm Co")
        self.establishment = Establishment.objects.create(
            name="Test Farm",
            company=self.company,
            state="CA",
        )

    def test_create_certification(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            created_by=self.user,
        )
        self.assertEqual(cert.verification_status, "pending")
        self.assertIsNotNone(cert.public_id)
        self.assertEqual(str(cert), "USDA Organic - Test Farm")

    def test_is_active_default(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
        )
        self.assertTrue(cert.is_active)

    def test_is_active_revoked(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="revoked",
        )
        self.assertFalse(cert.is_active)

    def test_is_active_suspended(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="suspended",
        )
        self.assertFalse(cert.is_active)

    def test_is_active_expired_date(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            expiry_date=date.today() - timedelta(days=1),
        )
        self.assertFalse(cert.is_active)

    def test_is_active_future_expiry(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            expiry_date=date.today() + timedelta(days=365),
        )
        self.assertTrue(cert.is_active)

    def test_is_verified(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
        )
        self.assertTrue(cert.is_verified)

    def test_is_not_verified(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="self_reported",
        )
        self.assertFalse(cert.is_verified)

    def test_consumer_display_status_verified(self):
        # The "Verified via USDA Organic Integrity Database" claim is gated on the
        # source that substantiates it (16 CFR 260.6), not on verification_status
        # alone — a status set by a manual edit or an import must not assert a
        # database match that never happened.
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )
        self.assertEqual(cert.consumer_display_status, "verified_via_database")

    def test_consumer_display_status_verified_without_a_source_stays_self_reported(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
        )
        self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_consumer_display_status_self_reported(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="self_reported",
        )
        self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_consumer_display_status_inactive(self):
        for s in ["expired", "revoked", "suspended"]:
            cert = Certification.objects.create(
                establishment=self.establishment,
                certification_type="other",
                verification_status=s,
                certification_number=f"test-{s}",
            )
            self.assertEqual(cert.consumer_display_status, "inactive")

    def test_consumer_display_status_pending(self):
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="pending",
        )
        self.assertEqual(cert.consumer_display_status, "pending")

    def test_unique_constraint(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certification_number="12345",
        )
        with self.assertRaises(Exception):
            Certification.objects.create(
                establishment=self.establishment,
                certification_type="usda_organic",
                certification_number="12345",
            )

    def test_multiple_certs_per_establishment(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
        )
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="fair_trade",
        )
        self.assertEqual(self.establishment.structured_certifications.count(), 2)


class CertificationVerificationLogTest(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Test Farm Co")
        self.establishment = Establishment.objects.create(
            name="Test Farm",
            company=self.company,
        )
        self.cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
        )

    def test_create_log(self):
        log = CertificationVerificationLog.objects.create(
            certification=self.cert,
            status_before="pending",
            status_after="verified",
            verification_source="usda_organic_integrity_db",
            success=True,
        )
        self.assertEqual(log.certification, self.cert)
        self.assertTrue(log.success)
        self.assertIsNotNone(log.attempted_at)

    def test_log_ordering(self):
        CertificationVerificationLog.objects.create(
            certification=self.cert,
            status_before="pending",
            status_after="self_reported",
            verification_source="none",
            success=False,
        )
        CertificationVerificationLog.objects.create(
            certification=self.cert,
            status_before="self_reported",
            status_after="verified",
            verification_source="usda_organic_integrity_db",
            success=True,
        )
        logs = list(self.cert.verification_logs.all())
        # Most recent first
        self.assertEqual(logs[0].status_after, "verified")
        self.assertEqual(logs[1].status_after, "self_reported")
