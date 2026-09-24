"""
3 CCR 6691 / DPR ENF 25-16 — the schoolsite answer must survive the REAL write path.

Two silent failure modes this guards, both found on 2026-09-18 after the field, the serializer
and the UI control were all individually correct:

1. `updateParcelCompliance` in `store/api/productApi.js` builds its FormData from an explicit
   ALLOWLIST of keys. A field missing from that list is dropped without a word, and the card
   still shows its success toast, so the farmer answers the question and nothing persists.
2. The card PATCHes multipart/form-data, which cannot carry a JSON null. "Not answered yet"
   therefore arrives as "", and DRF's BooleanField rejects "" by default.

Three states, not two. True, False and "never asked" are different facts on a filing the County
Agricultural Commissioner keys, so clearing back to unknown has to stay possible: the PUR export
reports an unanswered parcel as a gap and NEVER asserts it is clear of a schoolsite.
"""

from django.test import RequestFactory, TestCase

from company.models import Company, Establishment
from product.models import Parcel
from product.serializers import CreateParcelSerializer
from users.models import User


class SchoolsiteProximityRoundTripTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="school@test.com", password="x")
        company = Company.objects.create(name="Schoolsite Farm")
        self.establishment = Establishment.objects.create(name="SS1", company=company, state="CA")
        self.parcel = Parcel.objects.create(name="ss-parcel", establishment=self.establishment, area=16.2)

    def _patch(self, payload):
        request = RequestFactory().patch("/", data={})
        serializer = CreateParcelSerializer(
            instance=self.parcel, data=payload, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_starts_unanswered(self):
        """A parcel nobody has asked is None, never False."""
        self.assertIsNone(self.parcel.ca_near_schoolsite)

    def test_yes_round_trips(self):
        self.assertIs(self._patch({"ca_near_schoolsite": "true"}).ca_near_schoolsite, True)

    def test_no_round_trips(self):
        self.assertIs(self._patch({"ca_near_schoolsite": "false"}).ca_near_schoolsite, False)

    def test_blank_string_clears_back_to_unanswered(self):
        """The third state. Multipart sends "" for it, and it must not become False."""
        self._patch({"ca_near_schoolsite": "true"})
        self.parcel.refresh_from_db()
        self.assertIs(self.parcel.ca_near_schoolsite, True)
        cleared = self._patch({"ca_near_schoolsite": ""})
        self.assertIsNone(cleared.ca_near_schoolsite, '"" must clear to None, not coerce to False')

    def test_saving_the_site_id_does_not_clear_the_schoolsite_answer(self):
        """The two CA PUR facts share one card and one save button.

        This is the clobber class the pump/Site-ID split already produced once: a partial PATCH
        must leave the key it was not given alone.
        """
        self._patch({"ca_near_schoolsite": "true"})
        parcel = self._patch({"ca_site_id": "0001A"})
        self.assertEqual(parcel.ca_site_id, "0001A")
        self.assertIs(parcel.ca_near_schoolsite, True, "a Site ID save wiped the schoolsite answer")

    def test_saving_the_schoolsite_answer_does_not_clear_the_pump_test(self):
        """The mirror of the above, against the card's other editor block."""
        self._patch({"pump_efficiency_pct": "68.5", "pump_test_provider": "Valley Pump Testing"})
        parcel = self._patch({"ca_near_schoolsite": "false"})
        self.assertIs(parcel.ca_near_schoolsite, False)
        self.assertEqual(float(parcel.pump_efficiency_pct), 68.5)
        self.assertEqual(parcel.pump_test_provider, "Valley Pump Testing")

    def test_the_mutation_allowlist_carries_the_key(self):
        """Reads the ACTUAL client source, because the serializer being right proves nothing.

        `updateParcelCompliance` only appends keys named in its own list, so this field can be
        correct end to end on the server and still never arrive.
        """
        from pathlib import Path

        api = Path(__file__).resolve().parents[2].parent / "trazo-app" / "src" / "store" / "api" / "productApi.js"
        if not api.exists():  # the frontend repo is not checked out beside this one in CI
            self.skipTest(f"{api} not present")
        source = api.read_text()
        start = source.index("updateParcelCompliance")
        window = source[start : start + 2000]
        self.assertIn("'ca_near_schoolsite'", window, "the compliance mutation would drop the answer in silence")
