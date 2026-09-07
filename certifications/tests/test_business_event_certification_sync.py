"""
A certification event must save on an operation that holds two certificates of one type.

2026-09-06, found by the per-activity end-to-end sweep on the demo farm: it carries a verified
Cascadia USDA Organic row beside a pending CCOF one (a grower mid-switch between certifiers looks
exactly like this), and logging a "Certification & compliance" activity answered 500. The
post_save sync in certifications/signals.py did `get_or_create(establishment, certification_type)`
on a pair the model never made unique, so `MultipleObjectsReturned` escaped the request AFTER the
BusinessEvent row had been written — the wizard said "Failed to create event", the record existed
anyway, and a retry would have written a second one.
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import BusinessEvent, History
from product.models import Parcel, Product
from users.models import User


class BusinessEventCertificationSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="grower@test.com", password="x")
        company = Company.objects.create(name="Willamette Berry Co")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=company, state="OR")
        parcel = Parcel.objects.create(name="River Block", establishment=self.establishment, area=4.0)
        product = Product.objects.create(name="Blueberries")
        self.production = History.objects.create(
            name="2026 Dukes",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        self.verified = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="Cascadia Organic Certifiers",
            certification_number="COC-1001",
            verification_status="verified",
        )
        self.pending = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            certification_number="",
            verification_status="pending",
        )

    def _log(self, **fields):
        return BusinessEvent.objects.create(
            history=self.production,
            date=timezone.now(),
            business_type="certification",
            certification_type="organic_usda",
            description="Certification activity",
            **fields,
        )

    def test_saves_when_two_certificates_of_the_type_exist(self):
        event = self._log(verified_certifier_name="CCOF", certificate_number="CCOF-77")
        self.assertIsNotNone(event.pk)
        self.pending.refresh_from_db()
        self.assertEqual(
            self.pending.certification_number, "CCOF-77", "the event names CCOF: that row is the one it updates"
        )
        self.assertEqual(Certification.objects.filter(establishment=self.establishment).count(), 2)

    def test_a_verified_certificate_is_never_rewritten_by_a_self_reported_event(self):
        self._log(verified_certifier_name="Cascadia Organic Certifiers", certificate_number="TYPO-999")
        self.verified.refresh_from_db()
        self.assertEqual(self.verified.certification_number, "COC-1001")
        self.assertEqual(self.verified.verification_status, "verified")

    def test_a_new_certifier_is_a_new_certificate_not_a_correction(self):
        self._log(verified_certifier_name="Oregon Tilth", certificate_number="OT-5")
        rows = Certification.objects.filter(establishment=self.establishment, certification_type="usda_organic")
        self.assertEqual(rows.count(), 3)
        self.verified.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual(self.verified.certifier_name, "Cascadia Organic Certifiers")
        self.assertEqual(self.pending.certifier_name, "CCOF")

    def test_an_event_naming_nothing_attaches_to_the_existing_row(self):
        self._log()
        self.assertEqual(Certification.objects.filter(establishment=self.establishment).count(), 2)

    def test_first_event_on_a_farm_without_the_certificate_creates_it(self):
        Certification.objects.all().delete()
        self._log(verified_certifier_name="MOSA", certificate_number="M-1")
        cert = Certification.objects.get(establishment=self.establishment, certification_type="usda_organic")
        self.assertEqual(cert.certifier_name, "MOSA")
        self.assertEqual(cert.verification_status, "self_reported")
