"""F7 — a finished season header with a wrong number now has a correction path.

## What went wrong

`HistoryWriteSerializer._CLOSED_RECORD_FIELDS` freezes `production_amount`,
`production_unit`, `lot_id`, `quality_grade` and `harvest_method` once a season is
finished, and it is right to: the lot header is the traceability spine § 205.103(b)(2)
asks to be auditable back to the last certified operation. Events on that same season have
had `/amend` — original kept beside the correction, mandatory reason, printed in the
packet's "Documented Corrections" — since the amendments table shipped.

The header had NOTHING. A farmer who finished with the wrong yield could neither edit it
(the API answers 423) nor amend it. On the Calapooia Bend rehearsal that was not
hypothetical: the Finish form seeded `production_amount` from the latest event carrying a
yield, which on Duke 2025 was the BUFFER-ROW pick — 2,150 lb of explicitly non-organic
fruit standing in for a 118,750 lb certified lot (F6). The repair was a developer with ORM
access: a change to a filed record with nothing on paper behind it, which is the shape NOP
4002 calls concealment.

## What is pinned here

  1. The header can be corrected, the header carries the new value, and the amendment
     carries the original + actor + reason.
  2. A reason is mandatory, an unchanged value is refused, and a field outside the lot
     header is refused — `finish_date` above all, because re-dating a finished season
     is a reopen (it strands `retention_until`), not a correction.
  3. The row targets the HEADER: `event_type` and `event_id` are both NULL, and the DB
     constraint refuses half a target.
  4. Header corrections land in the SAME table as event corrections, so the packet prints
     one chronological list — and the event `/amend` GET does not pick them up.
  5. Ownership is asserted: a stranger cannot correct another operation's lot header.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company
from history.amendments import AmendmentError, apply_history_amendment
from history.constants import PRODUCTION_EVENT_TYPE
from history.models import EventAmendment, History, ProductionEvent
from product.models import Establishment, Parcel
from users.models import User, WorksIn


class SeasonHeaderAmendmentServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.user = User.objects.create_user(email="laurel@calapooiabend.example", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company)
        parcel = Parcel.objects.create(name="Home Field East", establishment=est, area=5.06)
        self.history = History.objects.create(
            parcel=parcel,
            name="Duke 2025 — Home Field East",
            finish_date=timezone.now() - timedelta(days=30),
            # The buffer-row number that F6 prefilled over the certified lot's own total.
            production_amount=2150,
            production_unit="lb",
            lot_id="CBF-25-HFE-01",
        )
        # Reload so `production_amount` is the float the DB actually holds (2150.0), not the
        # int this test typed. The rendered original in the packet comes from whatever is on
        # the instance, so testing against the in-memory literal would pin a string the
        # product never produces — `production_amount` is a FloatField, not a Decimal.
        self.history.refresh_from_db()

    def _amend(self, **kwargs):
        payload = {
            "history": self.history,
            "field_name": "production_amount",
            "new_value": "118750",
            "reason": "Header was prefilled from the buffer-row pick; scale tickets total 118,750 lb.",
            "user": self.user,
        }
        payload.update(kwargs)
        return apply_history_amendment(**payload)

    def test_the_header_carries_the_correction_and_the_row_carries_the_original(self):
        amendment = self._amend()

        self.history.refresh_from_db()
        self.assertEqual(self.history.production_amount, 118750.0)
        self.assertEqual(amendment.original_value, "2150.0")
        self.assertEqual(amendment.corrected_value, "118750.0")
        self.assertEqual(amendment.history_id, self.history.id)
        self.assertEqual(amendment.amended_by, self.user)
        self.assertIn("buffer-row", amendment.reason)

    def test_the_row_targets_the_header_not_an_event(self):
        """Both NULL is what makes this a header correction — the packet routes on it."""
        amendment = self._amend()
        self.assertIsNone(amendment.event_type)
        self.assertIsNone(amendment.event_id)
        self.assertTrue(amendment.targets_the_season_header)

    def test_the_row_carries_a_farmer_facing_label(self):
        """The packet prints `field_label`, and none of these columns declares a
        `verbose_name` — so the label used to come out as Django's derived "production
        amount": lowercase, underscored-looking, and not what the page beside it says."""
        amendment = self._amend()
        self.assertEqual(amendment.field_label, "Production amount")

    def test_a_reason_is_mandatory(self):
        with self.assertRaises(AmendmentError):
            self._amend(reason="   ")
        self.history.refresh_from_db()
        self.assertEqual(self.history.production_amount, 2150.0)

    def test_the_value_already_on_the_record_is_refused(self):
        with self.assertRaises(AmendmentError):
            self._amend(new_value="2150")

    def test_finish_date_is_not_correctable_here(self):
        """Re-dating a finished season is a REOPEN, not a correction.

        `retention_until` is computed once inside `History.finish()` and is read-only
        afterwards, so moving `finish_date` leaves the 5-year floor keyed to the old date —
        and clearing it releases every event lock on the season at once. That needs its own
        decision, not a text box labelled "correct this".
        """
        with self.assertRaises(AmendmentError):
            self._amend(field_name="finish_date", new_value="2025-01-01")

    def test_a_field_outside_the_lot_header_is_refused(self):
        with self.assertRaises(AmendmentError):
            self._amend(field_name="name", new_value="Something else")
        with self.assertRaises(AmendmentError):
            self._amend(field_name="parcel", new_value="1")

    def test_an_unparseable_value_is_refused_before_anything_is_written(self):
        with self.assertRaises(AmendmentError):
            self._amend(new_value="two thousand")
        self.history.refresh_from_db()
        self.assertEqual(self.history.production_amount, 2150.0)
        self.assertEqual(EventAmendment.objects.count(), 0)

    def test_half_a_target_is_refused_by_the_database(self):
        """A row with an event_type but no event_id points at nothing an inspector can look
        up, and the packet would print a correction against an unfindable record."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EventAmendment.objects.create(
                    event_type=PRODUCTION_EVENT_TYPE,
                    event_id=None,
                    history=self.history,
                    field_name="production_amount",
                    original_value="1",
                    corrected_value="2",
                    reason="half a target",
                )

    def test_header_and_event_corrections_share_one_table(self):
        """The packet's Documented Corrections section is one chronological list."""
        from history.amendments import apply_amendment

        event = ProductionEvent.objects.create(history=self.history, type="HA", date=timezone.now(), yield_quantity=200)
        apply_amendment(
            event=event,
            event_type=PRODUCTION_EVENT_TYPE,
            field_name="yield_quantity",
            new_value="2000",
            reason="Scale ticket reads 2,000 lb.",
            user=self.user,
        )
        self._amend()

        self.assertEqual(EventAmendment.objects.filter(history=self.history).count(), 2)


class SeasonHeaderAmendmentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.user = User.objects.create_user(email="laurel2@calapooiabend.example", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Calapooia Bend Farm", company=self.company)
        parcel = Parcel.objects.create(name="Home Field East", establishment=est, area=5.06)
        self.history = History.objects.create(
            parcel=parcel,
            name="Duke 2025",
            finish_date=timezone.now() - timedelta(days=30),
            production_amount=2150,
            production_unit="lb",
            lot_id="CBF-25-HFE-01",
        )
        self.history.refresh_from_db()
        self.url = f"/api/histories/{self.history.id}/amend/"

    def test_get_lists_the_correctable_header_fields(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200, resp.content)
        names = [f["name"] for f in resp.data["fields"]]
        self.assertEqual(
            names,
            ["production_amount", "production_unit", "lot_id", "quality_grade", "harvest_method"],
        )
        self.assertEqual(
            [f["label"] for f in resp.data["fields"]],
            ["Production amount", "Unit", "Lot ID", "Quality grade", "Harvest method"],
        )
        self.assertTrue(resp.data["is_finished"])
        self.assertEqual(resp.data["amendments"], [])

    def test_post_corrects_the_header_that_a_plain_patch_refuses(self):
        """The PATCH path answers 423-equivalent (400 from the closed-record guard); this
        one succeeds AND leaves a row explaining itself. That difference is the whole fix."""
        self.client.force_authenticate(user=self.user)

        refused = self.client.patch(
            f"/api/histories/{self.history.id}/", {"production_amount": "118750"}, format="json"
        )
        self.assertEqual(refused.status_code, 400, refused.content)

        resp = self.client.post(
            self.url,
            {
                "field_name": "production_amount",
                "new_value": "118750",
                "reason": "Header was prefilled from the buffer-row pick; tickets total 118,750 lb.",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.history.refresh_from_db()
        self.assertEqual(self.history.production_amount, 118750.0)
        self.assertEqual(resp.data["original_value"], "2150.0")

    def test_post_without_a_reason_is_refused(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(self.url, {"field_name": "lot_id", "new_value": "CBF-25-HFE-99"}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.history.refresh_from_db()
        self.assertEqual(self.history.lot_id, "CBF-25-HFE-01")

    def test_a_stranger_cannot_correct_this_operations_lot_header(self):
        stranger = User.objects.create_user(email="stranger@example.com", password="x")
        WorksIn.objects.create(
            user=stranger, company=Company.objects.create(name="Other Co"), role=WorksIn.COMPANY_ADMIN
        )
        self.client.force_authenticate(user=stranger)
        resp = self.client.post(
            self.url,
            {"field_name": "lot_id", "new_value": "STOLEN", "reason": "nope"},
            format="json",
        )
        # 404 since 2026-09-28: another company's season is not even found (tenancy floor).
        self.assertIn(resp.status_code, (403, 404), resp.content)
        self.history.refresh_from_db()
        self.assertEqual(self.history.lot_id, "CBF-25-HFE-01")

    def test_the_event_amend_endpoint_does_not_pick_up_header_corrections(self):
        """One table, two targets — the event sheet must still show only its own record."""
        self.client.force_authenticate(user=self.user)
        self.client.post(
            self.url,
            {"field_name": "lot_id", "new_value": "CBF-25-HFE-02", "reason": "Retyped from the tag."},
            format="json",
        )
        event = ProductionEvent.objects.create(history=self.history, type="HA", date=timezone.now(), yield_quantity=200)
        resp = self.client.get(f"/api/events/{event.id}/amend/?event_type={PRODUCTION_EVENT_TYPE}")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["amendments"], [])
