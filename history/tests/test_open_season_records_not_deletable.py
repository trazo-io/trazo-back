"""A season still being logged cannot be deleted with its records in it (OV-ST-C02, 2026-11-13).

`retention_until` is written when a season finishes, and a NULL one never blocked a delete. So a
pilot's whole first season, every activity logged since spring, could be erased with one confirm
on "Delete season", or with one API call on the parcel, farm or company above it. 7 CFR
205.103(b)(4) keeps records five years from their CREATION, and an activity is created when it is
logged. Pinned here, at every level, together with the two things that must stay possible: an
empty draft season still deletes, and a finished season deletes once its retention date passes.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import GeneralEvent, History, SalesRecord
from history.retention import RetentionConflict, assert_deletable, unfinished_histories_holding_records
from product.models import Parcel
from users.models import User, WorksIn


def cmd_unfinished(pk):
    return unfinished_histories_holding_records(pk=pk).exists()


class _Tree(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@open-season-delete.test", password="x")
        self.company = Company.objects.create(name="Open Season Co")
        self.farm = Establishment.objects.create(name="Home", company=self.company, state="WA")
        WorksIn.objects.create(user=self.owner, company=self.company, role="CA")
        self.parcel = Parcel.objects.create(name="North", establishment=self.farm, area=3.0)
        self.season = History.objects.create(parcel=self.parcel, name="2026 apples", start_date=timezone.now())
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def _log(self, season=None, n=1):
        for i in range(n):
            GeneralEvent.objects.create(
                history=season or self.season, name=f"walk {i}", description="scouting", date=timezone.now()
            )

    def _delete_season(self, season=None):
        return self.client.delete(reverse("productions-detail", args=[(season or self.season).pk]))

    def _delete_parcel(self):
        url = reverse(
            "establishment-parcels-detail",
            kwargs={"company_pk": self.company.pk, "establishment_pk": self.farm.pk, "pk": self.parcel.pk},
        )
        return self.client.delete(url)


class SeasonDeleteTests(_Tree):
    def test_an_open_season_with_activities_is_refused_and_kept(self):
        self._log(n=3)
        res = self._delete_season()
        self.assertEqual(res.status_code, 409, res.content)
        self.assertIn("3 records", res.json()["detail"])
        self.assertIn("205.103(b)(4)", res.json()["detail"])
        self.assertTrue(History.objects.filter(pk=self.season.pk).exists())
        self.assertEqual(GeneralEvent.objects.filter(history=self.season).count(), 3)

    def test_a_sale_alone_also_holds_the_season(self):
        SalesRecord.objects.create(
            production=self.season, buyer_name="Packer", quantity=10, sale_date=timezone.now().date()
        )
        with self.assertRaises(ValidationError):
            self.season.delete()
        self.assertTrue(History.objects.filter(pk=self.season.pk).exists())

    def test_an_empty_draft_still_deletes(self):
        res = self._delete_season()
        self.assertEqual(res.status_code, 204, res.content)
        self.assertFalse(History.objects.filter(pk=self.season.pk).exists())

    def test_deleting_the_activities_first_frees_the_season(self):
        """The way out for a season started by mistake: each activity delete is its own, logged act."""
        self._log(n=2)
        GeneralEvent.objects.filter(history=self.season).delete()
        self.assertEqual(self._delete_season().status_code, 204)

    def test_a_finished_season_past_retention_still_deletes(self):
        """The guard must not become a tombstone: a finished season follows its retention date."""
        self._log()
        History.objects.filter(pk=self.season.pk).update(
            finish_date=timezone.now() - timedelta(days=6 * 366),
            retention_until=timezone.now().date() - timedelta(days=1),
        )
        self.season.refresh_from_db()
        self.season.delete()
        self.assertFalse(History.objects.filter(pk=self.season.pk).exists())

    def test_a_legacy_finished_season_without_a_date_is_not_sent_to_a_locked_remedy(self):
        """Review on #422: keyed on a NULL retention date, a finished season from before that column
        existed was refused with "delete its activities first", and those are locked (423) once a
        season is finished. The new rule is about seasons not yet finished; this one is unchanged."""
        self._log()
        History.objects.filter(pk=self.season.pk).update(
            finish_date=timezone.now() - timedelta(days=30), retention_until=None
        )
        self.season.refresh_from_db()
        try:
            assert_deletable("parcel", parcel=self.parcel)
        except RetentionConflict as exc:
            self.fail(f"the parcel was refused with the unfinished-season rule: {exc.detail}")
        try:
            self.season.delete()
        except ValidationError as exc:
            self.fail(f"a finished season was refused with the unfinished-season rule: {exc}")

    def test_a_published_season_is_not_treated_as_open(self):
        self._log()
        History.objects.filter(pk=self.season.pk).update(published=True)
        self.season.refresh_from_db()
        self.assertFalse(cmd_unfinished(self.season.pk), "a published season's activities are locked; it is not open")


class ContainerDeleteTests(_Tree):
    def test_parcel_delete_is_refused_over_an_open_season_with_records(self):
        self._log(n=5)
        res = self._delete_parcel()
        self.assertEqual(res.status_code, 409, res.content)
        body = res.json()
        self.assertEqual(int(body["record_count"]), 5)  # DRF serialises APIException values as strings
        self.assertEqual(int(body["blocking_production_count"]), 1)
        self.assertIn("parcel", body["detail"])
        self.assertNotIn("retention_until", body, "an undated season must not answer the string 'None'")
        self.assertTrue(Parcel.objects.filter(pk=self.parcel.pk).exists())
        self.assertEqual(GeneralEvent.objects.filter(history=self.season).count(), 5)

    def test_farm_and_company_are_refused_too(self):
        self._log()
        with self.assertRaises(RetentionConflict):
            assert_deletable("farm", parcel__establishment=self.farm)
        with self.assertRaises(RetentionConflict):
            assert_deletable("company", parcel__establishment__company=self.company)

    def test_counts_cover_every_open_season_under_the_container(self):
        second = History.objects.create(parcel=self.parcel, name="2026 pears", start_date=timezone.now())
        self._log(n=2)
        self._log(season=second, n=1)
        with self.assertRaises(RetentionConflict) as ctx:
            assert_deletable("parcel", parcel=self.parcel)
        self.assertEqual(int(ctx.exception.detail["blocking_production_count"]), 2)
        self.assertEqual(int(ctx.exception.detail["record_count"]), 3)

    def test_a_parcel_with_only_an_empty_draft_still_deletes(self):
        self.assertEqual(self._delete_parcel().status_code, 204)
        self.assertFalse(Parcel.objects.filter(pk=self.parcel.pk).exists())
