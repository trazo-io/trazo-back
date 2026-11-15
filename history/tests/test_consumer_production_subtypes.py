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


class OwnerSeesWithheldSubtypesTests(TestCase):
    """The consumer filter must not run against the producer's own timeline.

    Found 2026-08-21. `may_publish_production_subtype` answers "may a CONSUMER surface show
    this?" — its own docstring says so — and `PublicHistorySerializer.get_events` applied it
    to EVERY caller, including the logged-in owner.

    The four withheld subtypes are not incidental: buffer disposition (§ 205.202(c)),
    the commercial-unavailability seed search (§ 205.204(a)(1)), equipment cleanout/purge and
    transport (§ 205.272) are all records the operator is REQUIRED to keep and the certifier
    explicitly asks for. So a farmer logged an equipment cleaning, watched it disappear from
    their production timeline, and had no way to know whether it saved. Measured on the
    rehearsal farm: a cleaning event already on a closed season was invisible to its own
    grower while the certifier packet (which builds from AuditExportService, not this
    serializer) rendered it the whole time.

    `_is_owner` is the boundary the rest of this serializer already uses, and
    `force_public_view` turns it off so the producer can preview the true shopper view.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from company.models import Company, Establishment
        from history.models import History, ProductionEvent
        from product.models import Parcel, Product

        User = get_user_model()
        cls.user = User.objects.create_user(email="subtypeowner@test.com", password="x")
        cls.company = Company.objects.create(name="Subtype Farm")
        cls.user.companies.add(cls.company)
        est = Establishment.objects.create(name="ST1", company=cls.company, state="WA")
        parcel = Parcel.objects.create(name="STP1", establishment=est, area=5.0)
        cls.history = History.objects.create(
            name="Subtype Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apple"),
            parcel=parcel,
            published=True,
        )
        for subtype in ("EM", "BU", "SS", "TP"):
            ProductionEvent.objects.create(
                history=cls.history,
                type=subtype,
                description=f"{subtype} record",
                date=timezone.now(),
            )
        ProductionEvent.objects.create(history=cls.history, type="HA", description="Harvest", date=timezone.now())

    def _production_subtypes(self, **context):
        from history.serializers import PublicHistorySerializer

        data = PublicHistorySerializer(self.history, context=context).data
        return {
            e.get("production_type") or e.get("type")
            for e in (data.get("events") or [])
            if isinstance(e, dict) and e.get("event_type") == 1
        }

    def _owner_request(self):
        from django.test import RequestFactory

        req = RequestFactory().get("/x/")
        req.user = self.user
        return req

    def test_the_owner_sees_every_subtype_they_recorded(self):
        subtypes = self._production_subtypes(request=self._owner_request())
        for withheld in ("EM", "BU", "SS", "TP"):
            self.assertIn(withheld, subtypes, f"the producer lost their own {withheld} record")

    def test_an_anonymous_consumer_sees_none_of_the_withheld_subtypes(self):
        """The half that must not regress — this is the claim-safety behaviour."""
        subtypes = self._production_subtypes()
        for withheld in ("EM", "BU", "SS", "TP"):
            self.assertNotIn(withheld, subtypes)
        self.assertIn("HA", subtypes, "ordinary field activity must still reach the QR page")

    def test_force_public_view_withholds_them_from_the_owner_too(self):
        """The producer previewing their own QR link must see exactly what a shopper sees."""
        subtypes = self._production_subtypes(request=self._owner_request(), force_public_view=True)
        for withheld in ("EM", "BU", "SS", "TP"):
            self.assertNotIn(withheld, subtypes)


CLEANOUT_NOTE = "Purged huller line S4-7731 with 40 lb of organic walnuts before the organic run"


class CleanoutNoteNeverReachesAShopperOverHttpTests(TestCase):
    """Run 8b (8b-04): an equipment cleanout's note is certifier-only, on the wire.

    The producer form now tells the farmer the cleanout note is not shown on the buyer page.
    That sentence is only true while the endpoints keep withholding EM whole, so this pins the
    HTTP responses a shopper actually receives, not the serializer in isolation.
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="cleanout-owner@test.com", password="x")
        cls.stranger = User.objects.create_user(email="cleanout-stranger@test.com", password="x")
        company = Company.objects.create(name="Cleanout Farm")
        cls.owner.companies.add(company)
        cls.stranger.companies.add(Company.objects.create(name="Some Other Farm"))
        est = Establishment.objects.create(name="CO1", company=company, state="WA")
        parcel = Parcel.objects.create(name="COP1", establishment=est, area=5.0)
        cls.history = History.objects.create(
            name="Cleanout Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Walnut"),
            parcel=parcel,
            published=True,
        )
        ProductionEvent.objects.create(
            history=cls.history,
            type="EM",
            date=timezone.now(),
            description="Equipment cleanout",
            observation=CLEANOUT_NOTE,
            created_by=cls.owner,
        )
        ProductionEvent.objects.create(
            history=cls.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            observation="Shook block 4",
            created_by=cls.owner,
        )

    def _get(self, url, user=None):
        from rest_framework.test import APIClient

        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        resp = client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.content.decode("utf-8")

    def _transparency(self, user=None):
        return self._get(f"/api/transparency/{self.history.public_id}/", user)

    def _public_history(self, user=None):
        return self._get(f"/api/productions/{self.history.public_id}/public_history/", user)

    def test_anonymous_shopper_never_receives_the_cleanout_note(self):
        for name, body in (("transparency", self._transparency()), ("public_history", self._public_history())):
            with self.subTest(endpoint=name):
                self.assertNotIn(CLEANOUT_NOTE, body)
                # The harvest beside it is served: the request read real events.
                self.assertIn("Shook block 4", body)

    def test_a_signed_in_non_owner_never_receives_the_cleanout_note(self):
        for name, body in (
            ("transparency", self._transparency(self.stranger)),
            ("public_history", self._public_history(self.stranger)),
        ):
            with self.subTest(endpoint=name):
                self.assertNotIn(CLEANOUT_NOTE, body)
                self.assertIn("Shook block 4", body)

    def test_the_owner_still_receives_it_on_their_own_production_feed(self):
        """ProfileProduction reads public_history; the grower must see the record they kept."""
        self.assertIn(CLEANOUT_NOTE, self._public_history(self.owner))

    def test_the_owner_gets_the_shopper_view_on_the_buyer_page_endpoint(self):
        """/api/transparency/ IS the consumer page and renders identically for everyone."""
        self.assertNotIn(CLEANOUT_NOTE, self._transparency(self.owner))


class ShopperEventCountsMatchWhatIsServedTests(TestCase):
    """Run 8b (X3): signed-in shopper counts count only what the public payload serves.

    `PublicHistorySerializer.get_events_count` counts what `get_events` serves. The shopper
    scan-history counts in serializers_consumer counted every ProductionEvent, so a production
    with a cleanout reported one more activity than its page showed.
    """

    @classmethod
    def setUpTestData(cls):
        from history.models import HistoryScan

        cls.shopper = User.objects.create_user(email="count-shopper@test.com", password="x")
        company = Company.objects.create(name="Count Farm")
        est = Establishment.objects.create(name="CF1", company=company, state="WA")
        parcel = Parcel.objects.create(name="CFP1", establishment=est, area=5.0)
        cls.history = History.objects.create(
            name="Count Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apple"),
            parcel=parcel,
            published=True,
        )
        for subtype in WITHHELD + ["HA", "IR"]:
            ProductionEvent.objects.create(
                history=cls.history, type=subtype, description=f"{subtype} record", date=timezone.now()
            )
        cls.scan = HistoryScan.objects.create(history=cls.history, user=cls.shopper)

    def _served(self):
        return PublicHistorySerializer(self.history).data["events_count"]

    def test_the_public_payload_serves_two(self):
        self.assertEqual(self._served(), 2)

    def test_count_events_for_history_matches_the_payload(self):
        from history.serializers_consumer import count_events_for_history

        self.assertEqual(count_events_for_history(self.history), self._served())

    def test_bulk_counts_match_the_payload(self):
        from history.serializers_consumer import get_bulk_event_counts

        self.assertEqual(get_bulk_event_counts([self.history.id]), {self.history.id: self._served()})

    def test_scan_history_events_viewed_matches_the_payload(self):
        from history.serializers_consumer import EnhancedHistoryScanSerializer

        self.assertEqual(EnhancedHistoryScanSerializer().get_events_viewed(self.scan), self._served())
