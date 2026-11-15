"""A Washington farm's spray records keep seven years (WAC 16-228-1320(3)), on top of the organic
five (7 CFR 205.103(b)(4)). Overall review 2026-11, OV-CMP-C08.

WAC 16-228-1320(3): pesticide application records "shall be kept for a period of seven years from
the date of the application". Trazo keeps retention per SEASON (`History.retention_until`, written
by `History.finish()` and moved forward by `history.retention.extend_retention`), so a Washington
season holding a pesticide, fungicide or herbicide record gets a floor of seven years after its
newest application. The later date wins: a state floor never brings a date forward, and a season
in another state, or one with no spray, keeps the five-year rule exactly as before.
"""

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rest_framework.test import APIClient, APIRequestFactory

from company.models import Company, Establishment
from history.models import ChemicalEvent, GeneralEvent, History, compute_retention_until
from history.retention import (
    RecordLocked,
    RetentionConflict,
    assert_child_record_deletable,
    assert_deletable,
    retention_floor,
    state_spray_retention_floor,
)
from product.models import Parcel, Product
from users.models import User, WorksIn

SPRAYED = datetime(2026, 6, 15, 7, 0, tzinfo=dt_tz.utc)
FINISHED = datetime(2026, 8, 12, 12, 0, tzinfo=dt_tz.utc)


class _Season(TestCase):
    def season(self, state, finished=True):
        company = Company.objects.create(name=f"{state} Orchard Co")
        farm = Establishment.objects.create(name=f"{state} farm", company=company, state=state)
        parcel = Parcel.objects.create(name="Block 1", establishment=farm, area=4.0)
        history = History.objects.create(
            name="2026 Apples",
            start_date=SPRAYED - timedelta(days=60),
            product=Product.objects.create(name="Apples"),
            parcel=parcel,
        )
        if finished:
            History.objects.filter(pk=history.pk).update(
                finish_date=FINISHED, retention_until=compute_retention_until(FINISHED)
            )
            history.refresh_from_db()
        return history

    def spray(self, history, when=SPRAYED, kind=ChemicalEvent.PESTICIDE):
        return ChemicalEvent.objects.create(
            history=history, type=kind, date=when, commercial_name="Entrust SC", description="spray"
        )


class WashingtonFloorTests(_Season):
    def test_a_washington_season_holding_a_spray_keeps_seven_years_from_the_application(self):
        history = self.season("WA")
        self.spray(history)
        self.assertEqual(state_spray_retention_floor(history), date(2033, 6, 15))
        self.assertEqual(retention_floor(history), date(2033, 6, 15))
        # The stored date moved with the record (post_save -> extend_retention), so the deletion
        # guard holds it.
        history.refresh_from_db()
        self.assertEqual(history.retention_until, date(2033, 6, 15))

    def test_the_newest_application_sets_the_date(self):
        history = self.season("WA")
        self.spray(history)
        self.spray(history, when=SPRAYED.replace(month=7, day=30), kind=ChemicalEvent.FUNGICIDE)
        self.assertEqual(retention_floor(history), date(2033, 7, 30))

    def test_finishing_a_washington_season_writes_the_seven_year_date(self):
        history = self.season("WA", finished=False)
        self.spray(history)
        history.finish({"finish_date": FINISHED.isoformat(), "production_amount": 10, "lot_id": "L-1"}, [])
        history.refresh_from_db()
        self.assertEqual(history.retention_until, date(2033, 6, 15))

    def test_a_california_season_stays_at_five_years(self):
        history = self.season("CA")
        self.spray(history)
        self.assertIsNone(state_spray_retention_floor(history))
        five = max(compute_retention_until(FINISHED), compute_retention_until(timezone.now().date()))
        self.assertEqual(retention_floor(history), five)
        self.assertLess(retention_floor(history), date(2033, 1, 1))

    def test_a_washington_season_without_a_spray_is_unaffected(self):
        history = self.season("WA")
        self.spray(history, kind=ChemicalEvent.FERTILIZER)
        GeneralEvent.objects.create(history=history, date=SPRAYED, description="pruning")
        self.assertIsNone(state_spray_retention_floor(history))
        self.assertLess(retention_floor(history), date(2033, 1, 1))

    def test_the_later_date_wins_so_the_state_floor_never_brings_a_date_forward(self):
        """A five-year date later than the state's (a record created years after the spray) stands."""
        history = self.season("WA")
        self.spray(history, when=datetime(2020, 5, 1, tzinfo=dt_tz.utc))
        self.assertEqual(state_spray_retention_floor(history), date(2027, 5, 1))
        self.assertGreaterEqual(retention_floor(history), compute_retention_until(FINISHED))


class RefusalsNameTheRuleTests(_Season):
    def test_a_refused_delete_names_the_washington_rule(self):
        history = self.season("WA")
        self.spray(history)
        history.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            history.delete()
        message = str(ctx.exception)
        self.assertIn("205.103(b)(4)", message)
        self.assertIn("WAC 16-228-1320(3)", message)
        self.assertIn("2033-06-15", message)

        with self.assertRaises(RetentionConflict) as ctx:
            assert_deletable("farm", parcel__establishment=history.parcel.establishment)
        self.assertIn("WAC 16-228-1320(3)", str(ctx.exception.detail))

    def test_a_california_refusal_does_not(self):
        history = self.season("CA")
        self.spray(history)
        history.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            history.delete()
        self.assertNotIn("WAC", str(ctx.exception))

    def test_a_stored_date_short_of_the_state_floor_is_held_to_it(self):
        """A season closed before the floor existed keeps its stored five-year date until a record
        moves it. The guard now holds the floor anyway (`effective_retention_until`), so the refusal
        states the floor's date and names the rule; it still states only the date the guard holds."""
        history = self.season("WA")
        self.spray(history)
        History.objects.filter(pk=history.pk).update(retention_until=compute_retention_until(FINISHED))
        history.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            history.delete()
        message = str(ctx.exception)
        self.assertIn("until 2033-06-15", message)
        self.assertIn("WAC 16-228-1320(3)", message)

    def test_a_stored_date_later_than_the_state_floor_is_not_credited_to_the_state(self):
        """A five-year date later than the state's (a record created years after the spray) is the
        organic rule's date, so the refusal does not cite the state rule for it."""
        history = self.season("WA")
        self.spray(history, when=datetime(2020, 5, 1, tzinfo=dt_tz.utc))
        history.refresh_from_db()
        self.assertGreater(history.retention_until, date(2027, 5, 1))
        with self.assertRaises(ValidationError) as ctx:
            history.delete()
        message = str(ctx.exception)
        self.assertIn(f"until {history.retention_until.isoformat()}", message)
        self.assertNotIn("WAC", message)

    def test_the_dossier_names_the_seven_years(self):
        from history.services.audit_export_service import _retention_detail

        history = self.season("WA")
        self.spray(history)
        history.refresh_from_db()
        text = _retention_detail([history], [history])
        self.assertIn("Kept until at least 2033-06-15", text)
        self.assertIn("seven years after its newest application (WAC 16-228-1320(3))", text)

        ca = self.season("CA")
        self.spray(ca)
        ca.refresh_from_db()
        self.assertNotIn("WAC", _retention_detail([ca], [ca]))


class SeasonsClosedBeforeTheFloorTests(_Season):
    """A Washington season that finished before #413 keeps its stored five-year date until a new
    record arrives, which for a finished season may be never. No data migration moves it: every
    reader that decides from the date reads the effective one instead, the later of the stored date
    and the seven-year floor computed now (`history.retention.effective_retention_until`). The
    stored column stays as it is.

    `effective_retention_until` is imported inside the tests that call it, so the behaviour tests
    run (and fail on their assertions) against code that does not have it.
    """

    FIVE = date(2031, 8, 12)  # compute_retention_until(FINISHED): what a pre-#413 season stores
    SEVEN = date(2033, 6, 15)  # seven years after SPRAYED (WAC 16-228-1320(3))
    BETWEEN = datetime(2032, 1, 1, 12, 0, tzinfo=dt_tz.utc)  # past the stored date, short of the floor
    AFTER = datetime(2033, 6, 16, 12, 0, tzinfo=dt_tz.utc)  # past both

    def closed_before_the_floor(self, state, kind=ChemicalEvent.PESTICIDE):
        history = self.season(state)
        self.spray(history, kind=kind)
        # The spray's post_save moved the stored date (`extend_retention`); put back the date a
        # season that finished before the floor existed still holds.
        History.objects.filter(pk=history.pk).update(retention_until=self.FIVE)
        history.refresh_from_db()
        return history

    def another_season(self, parcel, name):
        history = History.objects.create(
            name=name, start_date=SPRAYED - timedelta(days=60), product=Product.objects.create(name=name), parcel=parcel
        )
        self.spray(history)
        History.objects.filter(pk=history.pk).update(finish_date=FINISHED, retention_until=self.FIVE)
        return history

    def owner(self, history):
        user = User.objects.create_user(email=f"owner{history.pk}@orchard.example", password="x")
        WorksIn.objects.create(user=user, company=history.parcel.establishment.company, role=WorksIn.COMPANY_ADMIN)
        return user

    def assertStoredUntouched(self, history):
        self.assertEqual(History.objects.get(pk=history.pk).retention_until, self.FIVE)

    # --- Washington, with a spray ------------------------------------------------------------

    def test_the_effective_date_is_the_seven_year_floor(self):
        from history.retention import effective_retention_until

        history = self.closed_before_the_floor("WA")
        self.assertEqual(effective_retention_until(history), self.SEVEN)
        self.assertStoredUntouched(history)

    def test_delete_is_refused_past_the_stored_date_until_the_floor(self):
        history = self.closed_before_the_floor("WA")
        with mock.patch("django.utils.timezone.now", return_value=self.BETWEEN):
            with self.assertRaises(ValidationError) as ctx:
                history.delete()
        message = str(ctx.exception)
        self.assertIn("until 2033-06-15", message)
        self.assertIn("205.103(b)(4)", message)
        self.assertIn("WAC 16-228-1320(3)", message)
        self.assertNotIn("2031-08-12", message)
        self.assertStoredUntouched(history)

        with mock.patch("django.utils.timezone.now", return_value=self.AFTER):
            history.delete()
        self.assertFalse(History.objects.filter(pk=history.pk).exists())

    def test_a_farm_delete_is_refused_past_the_stored_date_until_the_floor(self):
        history = self.closed_before_the_floor("WA")
        farm = history.parcel.establishment
        with mock.patch("django.utils.timezone.now", return_value=self.BETWEEN):
            with self.assertRaises(RetentionConflict) as ctx:
                assert_deletable("farm", parcel__establishment=farm)
        detail = ctx.exception.detail
        self.assertEqual(str(detail["retention_until"]), "2033-06-15")
        self.assertIn("kept until 2033-06-15", str(detail["detail"]))
        self.assertIn("WAC 16-228-1320(3)", str(detail["detail"]))

        with mock.patch("django.utils.timezone.now", return_value=self.AFTER):
            assert_deletable("farm", parcel__establishment=farm)  # does not raise
        self.assertStoredUntouched(history)

    def test_the_container_check_does_not_query_per_season(self):
        """Two queries for the seasons and their floors, one for the refusal's sentence, whatever
        the number of seasons on the farm."""
        history = self.closed_before_the_floor("WA")
        farm = history.parcel.establishment

        def queries():
            with mock.patch("django.utils.timezone.now", return_value=self.BETWEEN):
                with CaptureQueriesContext(connection) as captured:
                    with self.assertRaises(RetentionConflict) as ctx:
                        assert_deletable("farm", parcel__establishment=farm)
            return len(captured), int(ctx.exception.detail["blocking_production_count"])

        one, count = queries()
        self.assertEqual(count, 1)
        for n in range(4):
            self.another_season(history.parcel, f"Pears {n}")
        many, count = queries()
        self.assertEqual(count, 5)
        self.assertEqual(many, one)

    def test_a_sale_lock_names_the_effective_date(self):
        history = self.closed_before_the_floor("WA")
        with self.assertRaises(RecordLocked) as ctx:
            assert_child_record_deletable("sales records", history)
        detail = ctx.exception.detail
        self.assertEqual(str(detail["retention_until"]), "2033-06-15")
        self.assertIn("until 2033-06-15", str(detail["detail"]))
        self.assertIn("WAC 16-228-1320(3)", str(detail["detail"]))

    def test_the_dossier_prints_the_effective_date(self):
        from history.services.audit_export_service import _retention_detail

        history = self.closed_before_the_floor("WA")
        text = _retention_detail([history], [history])
        self.assertIn("Kept until at least 2033-06-15", text)
        self.assertNotIn("2031-08-12", text)
        self.assertIn("seven years after its newest application (WAC 16-228-1320(3))", text)
        self.assertStoredUntouched(history)

    def test_the_api_refusal_names_the_effective_date(self):
        history = self.closed_before_the_floor("WA")
        client = APIClient()
        client.force_authenticate(user=self.owner(history))
        response = client.delete(f"/api/productions/{history.id}/")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.data["retention_until"], "2033-06-15")
        self.assertIn("WAC 16-228-1320(3)", response.data["detail"])
        self.assertStoredUntouched(history)

    def test_the_production_page_prints_the_effective_date(self):
        """The owner's production page prints `retention_until` as "Records retained until"."""
        from history.serializers import HistorySerializer, HistoryWriteSerializer, PublicHistorySerializer

        history = self.closed_before_the_floor("WA")
        self.assertEqual(HistorySerializer(history).data["retention_until"], "2033-06-15")
        self.assertEqual(HistoryWriteSerializer(history).data["retention_until"], "2033-06-15")

        request = APIRequestFactory().get("/")
        request.user = self.owner(history)
        owner_view = PublicHistorySerializer(history, context={"request": request}).data
        self.assertEqual(owner_view["retention_until"], "2033-06-15")
        # An anonymous QR scan still receives no retention date at all.
        self.assertNotIn("retention_until", PublicHistorySerializer(history).data)
        self.assertStoredUntouched(history)

    # --- The controls ------------------------------------------------------------------------

    def test_a_california_season_with_the_same_records_keeps_five_years(self):
        from history.retention import effective_retention_until
        from history.services.audit_export_service import _retention_detail

        history = self.closed_before_the_floor("CA")
        self.assertEqual(effective_retention_until(history), self.FIVE)
        with self.assertRaises(ValidationError) as ctx:
            history.delete()
        self.assertIn("until 2031-08-12", str(ctx.exception))
        self.assertNotIn("WAC", str(ctx.exception))
        self.assertNotIn("WAC", _retention_detail([history], [history]))

        with mock.patch("django.utils.timezone.now", return_value=self.BETWEEN):
            assert_deletable("farm", parcel__establishment=history.parcel.establishment)  # does not raise
            history.delete()
        self.assertFalse(History.objects.filter(pk=history.pk).exists())

    def test_a_washington_season_without_a_spray_is_unchanged(self):
        from history.retention import effective_retention_until

        history = self.closed_before_the_floor("WA", kind=ChemicalEvent.FERTILIZER)
        self.assertEqual(effective_retention_until(history), self.FIVE)
        self.assertStoredUntouched(history)
        with mock.patch("django.utils.timezone.now", return_value=self.BETWEEN):
            history.delete()
        self.assertFalse(History.objects.filter(pk=history.pk).exists())

    def test_an_open_season_still_has_no_date(self):
        """The floor does not give a season that never finished a retention date. Whether such a
        season can be deleted is #422's rule, not the floor's: it holds a record, so it cannot be
        deleted as a whole (#421 and #422 merged a minute apart, each green alone)."""
        from history.retention import effective_retention_until

        self.assertIsNone(effective_retention_until(None))
        history = self.season("WA", finished=False)
        self.spray(history)
        history.refresh_from_db()
        self.assertIsNone(history.retention_until)
        self.assertIsNone(effective_retention_until(history))
        with self.assertRaises(ValidationError):
            history.delete()
        self.assertTrue(History.objects.filter(pk=history.pk).exists())
