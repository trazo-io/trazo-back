"""
A pick sooner after raw manure on its parcel than the harvest interval of 7 CFR 205.203(c)(1).

WHY (2026-11-15, overall review OV-RK-C02): the conformance register cited
`ProductionEvent._validate_raw_manure_harvest_interval` as the harvest-side check. It runs only from the
model's `clean()`, which no API save calls, so a harvest logged inside the 90 or 120 days was compared
with the manure date nowhere, and the audit export compared the interval with the PLANNED harvest date.
`history/services/manure_check.py` compares the recorded picks.

Pinned here:
  * the boundary: a pick on day N of an N-day interval is outside it; a same-day pick is inside;
  * the interval is the longer of the recorded wait and the crop's minimum;
  * composted and documented NOP 5006 manure never count; undocumented "processed" manure does;
  * manure under an earlier season on the same parcel counts; another parcel's, or another block's
    when both name one, does not;
  * the save response carries `manure_conflicts` for a pick or a manure record, and no key otherwise;
    the record saves either way;
  * the season's readiness row says REVIEW with the first conflict as data.
"""

from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production, ProductionEvent, SoilManagementEvent
from history.services.manure_check import parcel_conflicts, season_conflicts
from product.models import Parcel, Product
from users.models import User, WorksIn


def _crop(slug, soil_contact):
    return CropType.objects.create(
        name=slug,
        slug=slug,
        category="tree_fruit",
        description="d",
        typical_farm_size="1",
        growing_season="s",
        harvest_season="h",
        emissions_per_hectare=0.0,
        industry_average=0.0,
        best_practice=0.0,
        carbon_credit_potential=0.0,
        typical_cost_per_hectare=0.0,
        has_soil_contact=soil_contact,
    )


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Manure Orchards LLC")
        self.user = User.objects.create_user(email="manure@test.com", password="x", first_name="Ana")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Manure Orchard", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="Lower Block", establishment=self.est, area=4.0)
        self.apples = _crop("apple-manure", False)  # 90 days, § 205.203(c)(1)(iii)
        self.season = self._season("Apples 2026", self.apples)

    def _season(self, name, crop, parcel=None):
        return Production.objects.create(
            parcel=parcel or self.parcel,
            product=Product.objects.create(name=name),
            name=name,
            crop_type=crop,
            start_date=timezone.make_aware(datetime(2026, 1, 1)),
        )

    def _manure(self, applied, interval="90", treatment="raw", block="", season=None, **extra):
        return SoilManagementEvent.objects.create(
            history=season or self.season,
            type="OM",
            description="manure",
            date=timezone.make_aware(datetime.combine(applied, datetime.min.time())),
            manure_application_date=applied,
            manure_harvest_interval=interval,
            manure_treatment=treatment,
            block_id=block,
            **extra,
        )

    def _pick(self, picked, kind="HA", block="", season=None):
        return ProductionEvent.objects.create(
            history=season or self.season,
            description="pick",
            date=timezone.make_aware(datetime.combine(picked, datetime.min.time().replace(hour=9))),
            type=kind,
            block_id=block,
        )


class ConflictTests(_Farm):
    def test_a_pick_inside_the_interval_is_found_and_one_on_its_last_day_is_not(self):
        manure = self._manure(date(2026, 4, 1))
        inside = self._pick(date(2026, 6, 20))  # day 80
        boundary = self._pick(date(2026, 6, 30))  # day 90
        found = parcel_conflicts(self.parcel.pk)
        self.assertEqual([(c.application_id, c.pick_id, c.days) for c in found], [(manure.pk, inside.pk, 80)])
        self.assertNotIn(boundary.pk, [c.pick_id for c in found])
        self.assertEqual(
            found[0].as_dict(),
            {
                "application_id": manure.pk,
                "pick_id": inside.pk,
                "applied": "2026-04-01",
                "picked": "2026-06-20",
                "days": 80,
                "interval_days": 90,
                "recorded_as": "raw",
            },
        )

    def test_a_same_day_pick_is_inside_and_a_pick_before_the_manure_is_not(self):
        self._manure(date(2026, 4, 1))
        same_day = self._pick(date(2026, 4, 1))
        self._pick(date(2026, 3, 20))
        self.assertEqual([c.pick_id for c in parcel_conflicts(self.parcel.pk)], [same_day.pk])

    def test_the_interval_is_the_longer_of_the_recorded_wait_and_the_crops_minimum(self):
        # 120 recorded on a tree crop: the farm is held to its own record.
        self._manure(date(2026, 4, 1), interval="120")
        self._pick(date(2026, 7, 10))  # day 100
        self.assertEqual([c.interval_days for c in parcel_conflicts(self.parcel.pk)], [120])

    def test_a_recorded_wait_shorter_than_the_minimum_never_lowers_it(self):
        squash = self._season("Squash 2026", _crop("squash-manure", True))  # 120 days, (c)(1)(ii)
        self._manure(date(2026, 4, 1), interval="90", season=squash)
        self._pick(date(2026, 7, 10), season=squash)  # day 100
        self.assertEqual([c.interval_days for c in parcel_conflicts(self.parcel.pk)], [120])

    def test_no_interval_recorded_uses_the_crops_minimum(self):
        for interval in ("na", None, ""):
            with self.subTest(interval=interval):
                SoilManagementEvent.objects.all().delete()
                ProductionEvent.objects.all().delete()
                self._manure(date(2026, 4, 1), interval=interval)
                self._pick(date(2026, 6, 20))
                self.assertEqual([c.interval_days for c in parcel_conflicts(self.parcel.pk)], [90])

    def test_compost_shown_to_meet_c2_bought_compost_and_documented_processed_manure_never_count(self):
        c2 = dict(compost_initial_cn_ratio=30, compost_peak_temp_f=140, compost_method="windrow")
        self._manure(
            date(2026, 4, 1), treatment="composted", compost_duration_days_at_temp=15, compost_turning_count=5, **c2
        )
        self._manure(
            date(2026, 4, 1),
            treatment="composted",
            compost_method="in_vessel",
            compost_initial_cn_ratio=28,
            compost_peak_temp_f=150,
            compost_duration_days_at_temp=3,
        )
        self._manure(date(2026, 4, 1), treatment="composted", amendment_supplier_name="Valley Compost Co")
        self._manure(date(2026, 4, 2), treatment="processed_5006", processed_manure_temp_f=165)
        self._manure(date(2026, 4, 3), treatment="processed_5006", processed_manure_attestation="OMRI listed")
        self._pick(date(2026, 4, 20))
        self.assertEqual(parcel_conflicts(self.parcel.pk), [])

    def test_a_composted_label_with_nothing_to_show_it_is_read_as_raw_and_says_so(self):
        """Review of back #446: the label alone exempted the record, while processed manure needed evidence."""
        cases = (
            ("no figures", {}),
            (
                "C:N outside 25 to 40",
                dict(
                    compost_initial_cn_ratio=45,
                    compost_peak_temp_f=140,
                    compost_method="windrow",
                    compost_duration_days_at_temp=15,
                    compost_turning_count=5,
                ),
            ),
            (
                "windrow short of 15 days",
                dict(
                    compost_initial_cn_ratio=30,
                    compost_peak_temp_f=140,
                    compost_method="windrow",
                    compost_duration_days_at_temp=10,
                    compost_turning_count=5,
                ),
            ),
            ("no method", dict(compost_initial_cn_ratio=30, compost_peak_temp_f=140, compost_duration_days_at_temp=20)),
        )
        for label, fields in cases:
            with self.subTest(label):
                SoilManagementEvent.objects.all().delete()
                ProductionEvent.objects.all().delete()
                manure = self._manure(date(2026, 4, 1), treatment="composted", **fields)
                self._pick(date(2026, 4, 20))
                found = parcel_conflicts(self.parcel.pk)
                self.assertEqual([(c.application_id, c.recorded_as) for c in found], [(manure.pk, "composted")])

    def test_undocumented_processed_manure_counts_as_raw(self):
        manure = self._manure(date(2026, 4, 1), treatment="processed_5006")
        self._pick(date(2026, 4, 20))
        self.assertEqual(
            [(c.application_id, c.recorded_as) for c in parcel_conflicts(self.parcel.pk)],
            [(manure.pk, "processed_5006")],
        )

    def test_manure_under_an_earlier_season_on_the_parcel_counts(self):
        last_year = self._season("Apples 2025", self.apples)
        manure = self._manure(date(2026, 1, 15), season=last_year)
        pick = self._pick(date(2026, 3, 1))
        found = season_conflicts(self.season)
        self.assertEqual([(c.application_id, c.pick_id) for c in found], [(manure.pk, pick.pk)])
        # The earlier season has no pick of its own, so it has nothing to report.
        self.assertEqual(season_conflicts(last_year), [])

    def test_another_parcel_or_another_named_block_does_not_count(self):
        other_parcel = Parcel.objects.create(name="Upper Block", establishment=self.est, area=2.0)
        self._manure(date(2026, 4, 1), season=self._season("Upper apples", self.apples, parcel=other_parcel))
        self._manure(date(2026, 4, 1), block="B2")
        self._pick(date(2026, 4, 20), block="B1")
        unnamed = self._pick(date(2026, 4, 21))
        self.assertEqual({c.pick_id for c in parcel_conflicts(self.parcel.pk)}, {unnamed.pk})


class SaveResponseTests(_Farm):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, event_type, **fields):
        payload = {"event_type": event_type, "history": self.season.id, "parcels": [self.parcel.id]}
        payload.update(fields)
        return self.client.post("/api/events/", payload, format="json")

    def test_a_pick_saved_inside_the_interval_saves_and_says_which_application(self):
        manure = self._manure(date(2026, 4, 1))
        res = self._post(
            1, type="HA", date=timezone.make_aware(datetime(2026, 6, 20, 9)).isoformat(), description="Pick"
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(
            [(c["application_id"], c["days"], c["interval_days"]) for c in res.data["manure_conflicts"]],
            [(manure.pk, 80, 90)],
        )

    def test_a_pick_outside_every_interval_says_so_with_an_empty_list(self):
        self._manure(date(2026, 4, 1))
        res = self._post(
            1, type="HA", date=timezone.make_aware(datetime(2026, 8, 1, 9)).isoformat(), description="Pick"
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data.get("manure_conflicts"), [])

    def test_a_record_that_is_neither_a_pick_nor_manure_carries_no_key(self):
        res = self._post(
            1,
            type="TP",
            date=timezone.make_aware(datetime(2026, 6, 20, 9)).isoformat(),
            description="Load",
            transportation_distance=10,
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertNotIn("manure_conflicts", res.data)


class ReadinessRowTests(_Farm):
    def _row(self):
        from history.services.audit_export_service import AuditExportService

        rows = AuditExportService(self.season, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if r["row_key"] == "raw_manure_interval")

    def test_an_early_pick_is_review_with_the_first_conflict_as_data(self):
        self._manure(date(2026, 4, 1))
        self._pick(date(2026, 6, 20))
        self._pick(date(2026, 6, 25))
        row = self._row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["detail_code"], "raw_manure_interval.harvest_inside")
        self.assertEqual(
            row["params"],
            {
                "count": 2,
                "applied": "2026-04-01",
                "picked": "2026-06-20",
                "days": 80,
                "interval": 90,
                "recorded_as": "raw",
            },
        )
        self.assertTrue(row["detail"].startswith("2 pick(s) on this production came sooner"), row["detail"])

    def test_manure_from_an_earlier_season_is_not_reported_as_no_manure(self):
        last_year = self._season("Apples 2025", self.apples)
        self._manure(date(2026, 1, 15), season=last_year)
        self._pick(date(2026, 3, 1))
        self.assertEqual(self._row()["status"], "REVIEW")

    def test_picks_after_the_interval_pass(self):
        self._manure(date(2026, 4, 1))
        self._pick(date(2026, 8, 1))
        self.assertEqual(self._row()["status"], "PASS")

    def test_an_interval_missing_on_this_seasons_manure_stays_the_fail_and_names_the_pick(self):
        """Review of back #446: the FAIL dropped the conflict it had found."""
        self._manure(date(2026, 4, 1), interval=None)
        self._pick(date(2026, 4, 20))
        row = self._row()
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["detail_code"], "raw_manure_interval.not_recorded_harvest_inside")
        self.assertEqual(
            row["params"],
            {
                "recorded": 0,
                "total": 1,
                "days": 90,
                "after": 19,
                "count": 1,
                "applied": "2026-04-01",
                "picked": "2026-04-20",
                "interval": 90,
                "recorded_as": "raw",
            },
        )
        self.assertIn("picked 2026-04-20, 19 day(s) after (interval 90 days)", row["detail"])

    def test_an_interval_missing_with_no_conflict_is_the_plain_fail(self):
        self._manure(date(2026, 4, 1), interval=None)
        self._pick(date(2026, 8, 20))
        row = self._row()
        self.assertEqual((row["status"], row["detail_code"]), ("FAIL", "raw_manure_interval.not_recorded"))

    def test_a_composted_label_with_nothing_to_show_it_says_so_in_the_row(self):
        self._manure(date(2026, 4, 1), treatment="composted")
        self._pick(date(2026, 4, 20))
        row = self._row()
        self.assertEqual((row["status"], row["params"]["recorded_as"]), ("REVIEW", "composted"))
        self.assertIn("recorded as composted, but the record carries neither", row["detail"])
