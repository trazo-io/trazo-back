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

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, GeneralEvent, History, compute_retention_until
from history.retention import RetentionConflict, assert_deletable, retention_floor, state_spray_retention_floor
from product.models import Parcel, Product

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

    def test_a_stored_date_short_of_the_state_floor_is_not_promised_it(self):
        """A season closed before the floor existed keeps its stored date until a record moves it;
        the refusal states the date the guard actually holds, never one it does not."""
        history = self.season("WA")
        self.spray(history)
        History.objects.filter(pk=history.pk).update(retention_until=compute_retention_until(FINISHED))
        history.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            history.delete()
        self.assertNotIn("WAC", str(ctx.exception))

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
