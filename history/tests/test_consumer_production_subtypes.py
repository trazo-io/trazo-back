"""Compliance records that read as their own opposite must not reach a shopper.

Four production subtypes are evidence of CORRECT practice and are read as an admission by an
audience that does not have the CFR open:

  * BU — § 205.202(c) REQUIRES buffer-zone crop to be sold non-organic. "Buffer rows cut, sold
    conventional" is the farmer doing exactly the right thing, about a DIFFERENT crop than the
    one scanned, and it reads as "part of this was not organic".
  * SS — the § 205.204(a)(1) commercial-unavailability search. "None could supply certified
    organic" is the documented allowance, and reads as "not fully organic".
  * EM — a line purge reveals split-operation handling out of the context that makes it a
    strength.
  * TP — names the operation's handler, which is commercial supply-chain information.

The STRUCTURED fields were already withheld from the anonymous payload. What was not withheld
was the farmer-authored name / description / observation, and for these four subtypes that free
text is the whole disclosure — verified against real events before this gate existed.

Withholding is not hiding a problem. All four stay in the certifier packet, which is where they
persuade the reader who can weigh them.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.serializers import PublicHistorySerializer
from history.services.claim_authority import may_publish_production_subtype
from product.models import Parcel, Product
from users.models import User

WITHHELD = ["BU", "SS", "EM", "TP"]
SHOWN = ["PL", "HA", "IR", "PR", "CU", "TH", "PO", "PH", "CM", "FP", "MO", "TR"]


class ConsumerProductionSubtypeGateTests(TestCase):
    def test_the_four_compliance_subtypes_are_withheld(self):
        for st in WITHHELD:
            with self.subTest(subtype=st):
                self.assertFalse(may_publish_production_subtype(st).allowed)

    def test_ordinary_field_activities_are_shown(self):
        """The mirror, and the one that matters commercially: a QR page exists to show these."""
        for st in SHOWN:
            with self.subTest(subtype=st):
                self.assertTrue(may_publish_production_subtype(st).allowed)

    def test_every_subtype_has_a_decision_recorded(self):
        """A new subtype must be classified deliberately, not defaulted silently.

        Allow-by-default is right for this gate — the alternative empties the QR page whenever
        a field activity is added — but that makes it the kind of default nobody notices. This
        reads the model vocabulary so a new subtype fails here until someone writes down which
        side it is on.
        """
        declared = {code for code, _ in ProductionEvent.PRODUCTION_EVENTS}
        decided = set(WITHHELD) | set(SHOWN)
        undecided = sorted(declared - decided)
        self.assertEqual(
            undecided,
            [],
            f"these production subtypes have no recorded consumer-visibility decision: "
            f"{undecided}. Add each to WITHHELD or SHOWN here, and to "
            f"_CONSUMER_WITHHELD_PRODUCTION_SUBTYPES in claim_authority.py if it is withheld.",
        )

    def test_case_and_whitespace_do_not_open_the_gate(self):
        for variant in ("bu", " BU ", "Bu"):
            self.assertFalse(may_publish_production_subtype(variant).allowed, variant)


class WithheldSubtypesAreAbsentFromThePayloadTests(TestCase):
    """The classification is worth nothing if the wire ignores it."""

    def setUp(self):
        user = User.objects.create_user(email="subtypegate@test.com", password="x")
        company = Company.objects.create(name="Subtype Gate Co")
        est = Establishment.objects.create(name="SG1", company=company)
        parcel = Parcel.objects.create(name="Block 4", establishment=est, area=6)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Gate Production",
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
        self.user = user

    def _public_types(self):
        data = PublicHistorySerializer(self.history).data
        return [str(e.get("type") or e.get("event_type")) for e in (data.get("events") or [])]

    def test_a_buffer_disposition_never_reaches_a_shopper(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="BU",
            date=timezone.now(),
            name="Buffer rows cut, sold conventional",
            description="Buffer rows cut, sold conventional",
            observation="North boundary rows adjacent to a conventional block.",
            buffer_disposition="sold_conventional",
            buffer_disposition_evidence="Delivery tag 8891",
            created_by=self.user,
        )
        self.assertNotIn("BU", self._public_types())
        payload = str(PublicHistorySerializer(self.history).data)
        # The free text was the actual disclosure — the structured fields were already withheld.
        self.assertNotIn("sold conventional", payload)
        self.assertNotIn("Delivery tag 8891", payload)

    def test_an_ordinary_harvest_still_reaches_the_shopper(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            created_by=self.user,
        )
        self.assertIn("HA", self._public_types())
