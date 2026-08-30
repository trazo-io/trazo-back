"""
Sprint 5A tests — ConsumerClaimValidator (QR page organic-claim gate).

Covers the four regulated scenarios:
  1. Active verified USDA Organic cert -> can display "Organic"
  2. No cert, in 36-month transition -> "Transitioning"
  3. Farmer claims organic method but no cert -> "Self-Reported (Not Certified)"
  4. No cert, no claim -> "Conventional"

Regulatory basis: 7 CFR 205.100(c)(1), 7 CFR 205.300, 7 CFR 205.202(b),
16 CFR 260.6(c)-(d). Each test is labeled with the rule it's enforcing.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from certifications.models import Certification
from certifications.services.consumer_claim_validator import ConsumerClaimValidator, filter_certifications_for_consumer
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, ParcelCropHistory, Product
from users.models import User


class ConsumerClaimValidatorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="cc@test.com", password="x")
        self.company = Company.objects.create(name="Claim Farm")
        self.establishment = Establishment.objects.create(name="Field", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        self.product = Product.objects.create(name="Tomato")

    def _make_history(self, production_method="conventional"):
        return History.objects.create(
            name="H",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            production_method=production_method,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    # ---- Scenario 1: Certified Organic -------------------------------------

    def test_active_verified_usda_organic_allows_organic_claim(self):
        """7 CFR 205.100(c)(1): only certified operations may be sold as organic."""
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            certifier_name="CCOF",
            effective_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
        )
        history = self._make_history(production_method="organic")

        result = ConsumerClaimValidator().validate(history)

        self.assertTrue(result.can_display_organic)
        self.assertFalse(result.can_display_transitioning)
        self.assertEqual(result.status, "certified_organic")
        self.assertEqual(result.status_color, "green")
        self.assertIn("USDA", result.display_label)

    # ---- Scenario 2: Transitioning -----------------------------------------

    def test_in_transition_blocks_organic_shows_transitioning(self):
        """7 CFR 205.202(b): pre-36-month land cannot be labeled organic."""
        # Declared prohibited substance 12 months ago -> well inside transition.
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=timezone.now().year - 1,
            crop_grown="Corn",
            date_last_prohibited=timezone.now().date() - timedelta(days=365),
        )
        history = self._make_history(production_method="organic")

        result = ConsumerClaimValidator().validate(history)

        self.assertFalse(result.can_display_organic)
        self.assertTrue(result.can_display_transitioning)
        self.assertEqual(result.status, "transitioning")
        self.assertEqual(result.status_color, "yellow")
        self.assertIn("Transition", result.display_label)
        # 16 CFR 260.6(d): disclaimer must disclose basis.
        self.assertIn("transition", result.disclaimer.lower())

    # ---- Scenario 3: Self-reported organic, no cert ------------------------

    def test_self_reported_organic_without_cert_blocks_usda_badge(self):
        """
        7 CFR 205.300: products may not be represented as organic without
        certification. Farmer typed production_method='organic' but has no cert
        and no transition record — must show "self-reported", not "Certified".
        """
        history = self._make_history(production_method="organic")

        result = ConsumerClaimValidator().validate(history)

        self.assertFalse(result.can_display_organic)
        self.assertFalse(result.can_display_transitioning)
        self.assertEqual(result.status, "self_reported")
        self.assertIn("farmer", result.display_label.lower())
        self.assertIn("not", result.disclaimer.lower())  # "Not independently verified"

    # ---- Scenario 4: Conventional ------------------------------------------

    def test_conventional_production_shows_conventional(self):
        history = self._make_history(production_method="conventional")
        result = ConsumerClaimValidator().validate(history)
        self.assertFalse(result.can_display_organic)
        self.assertFalse(result.can_display_transitioning)
        self.assertEqual(result.status, "conventional")

    # ---- Edge cases --------------------------------------------------------

    def test_expired_cert_does_not_allow_organic_claim(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            effective_date=timezone.now().date() - timedelta(days=730),
            expiry_date=timezone.now().date() - timedelta(days=30),  # Expired
        )
        history = self._make_history(production_method="organic")
        result = ConsumerClaimValidator().validate(history)
        self.assertFalse(result.can_display_organic)
        # Falls through to self-reported since method='organic' is set.
        self.assertEqual(result.status, "self_reported")

    def test_self_reported_cert_does_not_trigger_certified_status(self):
        """
        Certification with verification_status='self_reported' is NOT the same as
        a verified USDA cert — must not be treated as valid for the QR badge.
        """
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="self_reported",
            certifier_name="(self-reported)",
        )
        history = self._make_history(production_method="organic")
        result = ConsumerClaimValidator().validate(history)
        self.assertFalse(result.can_display_organic)
        self.assertEqual(result.status, "self_reported")

    def test_filter_certifications_strips_unverified_usda_organic(self):
        """The badge filter must mirror the claim gate — no drift between them."""
        verified_usda = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            expiry_date=timezone.now().date() + timedelta(days=30),
        )
        self_reported_usda = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="self_reported",
        )
        # A non-USDA certification. Was "ccof" until 2026-08-27, which never belonged in the
        # type column at all — CCOF is a certifying AGENT that ISSUES USDA Organic, so the
        # row it built was not the "non-USDA" case this test claims to cover.
        other_cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="rainforest_alliance",
            verification_status="self_reported",
        )
        filtered = filter_certifications_for_consumer([verified_usda, self_reported_usda, other_cert])
        ids = {c.id for c in filtered}
        self.assertIn(verified_usda.id, ids)
        self.assertNotIn(self_reported_usda.id, ids)  # Unverified USDA stripped
        self.assertIn(other_cert.id, ids)  # Non-USDA self-reported passes through
