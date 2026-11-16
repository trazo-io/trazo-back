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
from certifications.services.consumer_claim_validator import (
    DISCLAIMER_MESSAGE_IDS,
    ConsumerClaimValidator,
    filter_certifications_for_consumer,
)
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
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
        return Production.objects.create(
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

    def test_certified_without_oid_match_does_not_claim_database_verification(self):
        """16 CFR 260.6 — the disclaimer names an act Trazo must actually have performed.

        `Certification.consumer_display_status` already refuses to call a row
        `verified_via_database` unless `verification_source` is the OID, so the certifications
        list beside this claim renders "self_reported". Until 2026-08-30 the claim block did not
        consult that gate at all: a fixture row marked `verification_status="verified"` by hand
        produced "Verification via USDA Organic Integrity Database" on a public page where no
        such match had ever run. Solana Verde served exactly that contradiction in production.
        """
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            certifier_name="Pacific Slope Organic Certifiers (DEMO)",
            effective_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
        )
        self.assertEqual(cert.consumer_display_status, "self_reported")

        result = ConsumerClaimValidator().validate(self._make_history(production_method="organic"))

        # The affirmative sentence is the claim; the phrase alone is not, because the honest
        # text names the database in order to DENY the match. Assert on the claim.
        self.assertNotIn("Verification via USDA Organic Integrity Database", result.disclaimer)
        # The PROPERTY, not the phrasing: the qualification has to be in the first sentence.
        # This string renders in a clamped popover, so a denial that appears only after a
        # truncation point is not a denial. Asserted on the leading clause rather than an exact
        # literal, because the wording was corrected once already (the first version said "Not
        # verified by Trazo against …", which wrongly implied Trazo does not run the match).
        first_sentence = result.disclaimer.split(".")[0]
        self.assertIn(
            "Not matched",
            first_sentence,
            f"the qualification must lead, not trail: {result.disclaimer!r}",
        )
        self.assertIn("certificate on file", result.disclaimer)

    def test_certified_with_oid_match_keeps_the_database_disclaimer(self):
        """The other direction, and the reason the label was left alone.

        A real OID match is the one case where the sentence is true, and downgrading it would
        strip a legitimate grower of the strongest honest claim they have.
        """
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
            certifier_name="CCOF",
            effective_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
        )
        self.assertEqual(cert.consumer_display_status, "verified_via_database")

        result = ConsumerClaimValidator().validate(self._make_history(production_method="organic"))

        self.assertIn("USDA Organic Integrity Database", result.disclaimer)

    def test_unmatched_certificate_is_never_called_not_certified(self):
        """The over-correction this fix deliberately avoided.

        Routing the unsubstantiated case into DISCLAIMER_SELF_REPORTED would have ended the
        sentence "Not USDA Certified Organic" — false about an operation that holds a
        certificate, and a claim the farm could reasonably object to.
        """
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            certifier_name="Pacific Slope Organic Certifiers (DEMO)",
            effective_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
        )

        result = ConsumerClaimValidator().validate(self._make_history(production_method="organic"))

        self.assertNotIn("Not USDA Certified Organic", result.disclaimer)
        self.assertEqual(result.status, "certified_organic")
        self.assertTrue(result.can_display_organic)

    def test_every_reachable_disclaimer_ships_a_message_id(self):
        """No consumer-visible qualification may be English-only.

        `disclaimer_key` is derived from a lookup on the string itself, so a new disclaimer
        added without a matching entry produces `disclaimer_key: None` and silently falls back
        to raw server English inside a Spanish page — the state this fix removed, reappearing
        the next time someone adds a claim state.

        Each branch is evaluated AT ITS POINT IN THE SEQUENCE. Collecting the histories first
        and validating them at the end does not work: the validator reads the establishment's
        certifications live, so every case ends up seeing whatever certificate exists last, and
        all four collapse onto one disclaimer.
        """
        seen = {}

        seen["conventional"] = (
            ConsumerClaimValidator().validate(self._make_history(production_method="conventional")).to_dict()
        )
        seen["self_reported"] = (
            ConsumerClaimValidator().validate(self._make_history(production_method="organic")).to_dict()
        )

        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            certifier_name="On File Only",
            effective_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
        )
        seen["certified_on_file"] = (
            ConsumerClaimValidator().validate(self._make_history(production_method="organic")).to_dict()
        )

        cert.verification_source = Certification.DATABASE_VERIFICATION_SOURCE
        cert.save(update_fields=["verification_source"])
        seen["certified_oid"] = (
            ConsumerClaimValidator().validate(self._make_history(production_method="organic")).to_dict()
        )

        for name, payload in seen.items():
            self.assertIsNotNone(
                payload.get("disclaimer_key"),
                f"{name}: disclaimer {payload['disclaimer']!r} has no entry in "
                "DISCLAIMER_MESSAGE_IDS, so a non-English consumer reads it in English",
            )

        keys = {payload["disclaimer_key"] for payload in seen.values()}
        # Anti-vacuity. Without this the loop above passes while exercising a single path —
        # which is exactly what it did on the first run of this test. The two certified
        # branches in particular MUST differ: that difference is the 16 CFR 260.6 fix.
        self.assertEqual(len(keys), 4, f"branches collapsed; only reached {sorted(keys)}")
        self.assertNotEqual(
            seen["certified_on_file"]["disclaimer_key"],
            seen["certified_oid"]["disclaimer_key"],
        )
        self.assertTrue(keys.issubset(set(DISCLAIMER_MESSAGE_IDS.values())))

    def test_oid_matched_travels_with_the_claim(self):
        """One authority for "did the match happen", consumed by four surfaces.

        The pill, the OID attribution line, `evidence.source` and the disclaimer each used to
        decide this for themselves — three of the four from `status == "certified_organic"`,
        which only means a certificate ROW exists. `oid_matched` is the fact the public
        /methodology page's promise is written about, computed once here.
        """
        cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            verification_status="verified",
            certifier_name="On File Only",
            effective_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=300),
        )
        unmatched = ConsumerClaimValidator().validate(self._make_history(production_method="organic")).to_dict()
        self.assertEqual(unmatched["status"], "certified_organic")
        self.assertFalse(
            unmatched["oid_matched"],
            "a certificate with no OID source must not report a database match",
        )

        cert.verification_source = Certification.DATABASE_VERIFICATION_SOURCE
        cert.save(update_fields=["verification_source"])
        matched = ConsumerClaimValidator().validate(self._make_history(production_method="organic")).to_dict()
        self.assertTrue(matched["oid_matched"])

    def test_uncertified_claims_never_report_a_match(self):
        """`oid_matched` is False for every other tier — no surface may read it as unset."""
        for method in ("organic", "conventional"):
            payload = ConsumerClaimValidator().validate(self._make_history(production_method=method)).to_dict()
            self.assertIn("oid_matched", payload, method)
            self.assertFalse(payload["oid_matched"], method)

    def test_evidence_source_names_the_oid_only_on_a_match(self):
        """`evidence.source` is on the ANONYMOUS payload, so the string itself is the claim."""
        from history.services.claim_resolver import LotOrganicEligibility, build_organic_claim_evidence

        ineligible = LotOrganicEligibility(
            eligible=None,
            status="not_applicable",
            display_label="",
            detail="",
            prohibited_inputs=[],
            unclassified_input_count=0,
            checked_at=None,
        )

        unmatched = build_organic_claim_evidence({"status": "certified_organic", "oid_matched": False}, ineligible)
        self.assertNotIn("Integrity Database", unmatched["source"])

        matched = build_organic_claim_evidence({"status": "certified_organic", "oid_matched": True}, ineligible)
        self.assertEqual(matched["source"], "USDA Organic Integrity Database")

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
