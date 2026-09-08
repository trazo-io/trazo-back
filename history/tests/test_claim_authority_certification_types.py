"""Which certification types may reach a shopper — and the check that keeps it decided.

WHY THIS FILE EXISTS
--------------------
`BusinessEvent.CERTIFICATION_TYPE_CHOICES` offered `carbon_neutral` ("Carbon Neutral
Certification"), and `PublicHistorySerializer.get_events()` put `certification_type` and its
display label on the anonymous payload. A farm could select it and a shopper would see it.

The existing gate was not wrong, it was answering a different question.
`may_claim_certifier_attestation` labels any non-USDA certification "Self-Reported", which is
the correct and sufficient treatment for "Rainforest Alliance" — a named programme, qualified
as the operation's own statement. It does not cure "Carbon Neutral": FTC 16 CFR 260.4 governs
general environmental benefit claims themselves (260.6 is certifications and seals), and
ECGT 2024/825 (live 2026-09-27) bans
self-created sustainability labels outright. "Carbon Neutral — Self-Reported" is still a
net-zero claim on a public product page.

THE POINT OF THE EXHAUSTIVENESS TEST
------------------------------------
`claim-authority-chokepoint` records the lesson that a denylist encodes only the LAST incident.
Hiding the string "carbon_neutral" would leave the next entry to publish itself by default. So
`may_publish_certification_type` fails closed on anything it has not seen, and the first test
below fails the moment either model vocabulary grows a value the module has not classified.
That is what converts "we removed one bad label" into "a new label cannot ship undecided".
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import BusinessEvent, History
from history.serializers import PublicHistorySerializer
from history.services.claim_authority import (
    _PUBLISHABLE_CERTIFICATION_TYPES,
    _WITHHELD_CERTIFICATION_TYPES,
    may_publish_certification_type,
)
from product.models import Parcel, Product
from users.models import User


class CertificationTypeClassificationTests(TestCase):
    def test_every_certification_type_in_both_vocabularies_is_classified(self):
        """The guard that makes fail-closed a design rather than an accident.

        Both lists are read from the models themselves, so adding a certification type
        anywhere fails here until someone decides whether a shopper may see it.
        """
        from certifications.constants import CERTIFICATION_TYPE_CHOICES as CERT_APP_CHOICES

        classified = set(_PUBLISHABLE_CERTIFICATION_TYPES) | set(_WITHHELD_CERTIFICATION_TYPES)
        declared = {c[0] for c in BusinessEvent.CERTIFICATION_TYPE_CHOICES} | {c[0] for c in CERT_APP_CHOICES}
        unclassified = sorted(declared - classified)
        self.assertEqual(
            unclassified,
            [],
            "these certification types are offered by a model but not classified in "
            "claim_authority.py, so they are silently withheld from consumers: "
            f"{unclassified}. Decide each one — publishable (names an issuing body or a "
            "specific checkable attribute) or withheld (asserts a general environmental "
            "benefit with nothing behind it).",
        )

    def test_the_two_lists_never_overlap(self):
        overlap = sorted(set(_PUBLISHABLE_CERTIFICATION_TYPES) & set(_WITHHELD_CERTIFICATION_TYPES))
        self.assertEqual(overlap, [], f"a type is both publishable and withheld: {overlap}")

    def test_carbon_neutral_is_withheld(self):
        decision = may_publish_certification_type("carbon_neutral")
        self.assertFalse(decision.allowed)
        # 16 CFR 260.4 is general environmental benefit claims; 260.6 is certifications and
        # seals. This assertion pinned 260.6 and so demanded the miscitation the 2026-09-07
        # sweep corrected across 23 sites — a red guard that asks for the wrong rule.
        self.assertIn("260.4", decision.reason)
        self.assertNotIn("260.6", decision.reason)

    def test_a_named_programme_is_publishable(self):
        """The mirror. Without it, withholding everything would also pass."""
        self.assertTrue(may_publish_certification_type("rainforest_alliance").allowed)
        self.assertTrue(may_publish_certification_type("global_gap").allowed)

    def test_an_unknown_type_fails_closed(self):
        self.assertFalse(may_publish_certification_type("some_new_eco_label").allowed)
        self.assertFalse(may_publish_certification_type(None).allowed)

    def test_case_and_whitespace_do_not_open_the_gate(self):
        """A stored value with stray casing must not slip past as 'unclassified but harmless'."""
        for variant in ("Carbon_Neutral", "  carbon_neutral  ", "CARBON_NEUTRAL"):
            self.assertFalse(
                may_publish_certification_type(variant).allowed,
                f"{variant!r} reached a public surface",
            )


class WithheldCertificationDoesNotReachTheAnonymousPayloadTests(TestCase):
    """End to end: the classification is worth nothing if the wire ignores it."""

    def setUp(self):
        user = User.objects.create_user(email="certgate@test.com", password="x")
        company = Company.objects.create(name="Cert Gate Co")
        establishment = Establishment.objects.create(name="CG1", company=company)
        parcel = Parcel.objects.create(name="Block 3", establishment=establishment, area=5)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Cert Gate Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _public_events(self):
        return PublicHistorySerializer(self.history).data.get("events") or []

    def _business_event(self, certification_type):
        BusinessEvent.objects.create(
            history=self.history,
            type=BusinessEvent.CERTIFICATION,
            business_type="certification",
            certification_type=certification_type,
            date=timezone.now(),
        )

    def test_carbon_neutral_is_absent_from_the_shopper_payload(self):
        self._business_event("carbon_neutral")
        events = self._public_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIsNone(ev.get("certification_type"))
        self.assertIsNone(ev.get("certification_type_display"))
        # Belt and braces: the phrase itself must not appear anywhere in the payload, however
        # some other key chooses to render it.
        self.assertNotIn("carbon neutral", str(ev).lower())

    def test_a_named_programme_still_reaches_the_shopper(self):
        """The mirror again, and the one that matters commercially: this gate must not quietly
        strip the certifications a farm is entitled to show."""
        self._business_event("rainforest_alliance")
        events = self._public_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get("certification_type"), "rainforest_alliance")
        self.assertTrue(events[0].get("certification_type_display"))


class BothPublicSurfacesHonourTheVerdictTests(TestCase):
    """A chokepoint consulted by one of two public surfaces is not a chokepoint.

    `filter_certifications_for_consumer` policed only the USDA Organic badge and documented
    that everything else "passes through unchanged" — so the /api/transparency/ certification
    list would still have carried a label the event payload had already learned to withhold.
    The two vocabularies differ (`usda_organic` here, `organic_usda` on the event), which is
    exactly why this needed testing on the real objects rather than reasoned about.
    """

    def setUp(self):
        company = Company.objects.create(name="Two Surfaces Co")
        self.establishment = Establishment.objects.create(name="TS1", company=company)

    def _cert(self, certification_type):
        from certifications.models import Certification

        return Certification.objects.create(
            establishment=self.establishment,
            certification_type=certification_type,
            verification_status="self_reported",
        )

    def test_a_withheld_type_is_stripped_from_the_consumer_certification_list(self):
        from certifications.services.consumer_claim_validator import filter_certifications_for_consumer

        # Written directly: no model vocabulary offers this today, which is the point — the
        # gate must hold for a value added later, not only for the one that prompted it.
        rogue = self._cert("carbon_neutral")
        kept = self._cert("rainforest_alliance")
        out = filter_certifications_for_consumer([rogue, kept])
        self.assertEqual([c.certification_type for c in out], ["rainforest_alliance"])

    def test_named_programmes_survive_the_filter(self):
        from certifications.services.consumer_claim_validator import filter_certifications_for_consumer

        certs = [self._cert(t) for t in ("primus_gfs", "global_gap", "fair_trade", "roc")]
        out = filter_certifications_for_consumer(certs)
        self.assertEqual(len(out), 4, "the gate stripped certifications a farm may legitimately show")
