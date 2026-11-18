"""Tree nuts swept from the orchard floor: the 90-day floor holds, and an interval under 120 days is put to the
certifier (2026-11-18).

7 CFR 205.203(c)(1) turns on whether the EDIBLE PORTION touches the soil. The kernel of a walnut, almond, pecan
or hazelnut does not, so (c)(1)(iii) sets 90 days. The shell lies on the ground for days before it is swept,
and a certifier can read that as soil contact under (c)(1)(ii), 120 days. Nothing from CCOF, OTCO or WSDA
settles it. So nothing is refused, and the dossier names both readings when raw manure under 120 days meets
one of these crops and no pick, or planned harvest, shows 120 days were kept anyway. Pistachios are caught on
frames and are not marked.
"""

import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from history.models import ProductionEvent, SoilManagementEvent
from history.services.manure_check import ground_harvest_reviews
from history.services.manure_interval import gathered_from_ground, minimum_interval_days
from history.tests.test_manure_interval_is_a_floor import _crop, _Production

GROUND = {"walnuts", "almonds", "pecans", "hazelnuts"}


class TheSeededNutsSweptFromTheGroundAreMarked(TestCase):
    def test_the_seeder_marks_the_four_ground_harvested_nuts_and_nothing_else(self):
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        marked = set(CropType.objects.filter(harvested_from_ground=True).values_list("slug", flat=True))
        self.assertEqual(marked, GROUND)
        for slug in GROUND:
            crop = CropType.objects.get(slug=slug)
            self.assertTrue(gathered_from_ground(crop), slug)
            self.assertEqual(minimum_interval_days(crop), 90, slug)
        self.assertFalse(gathered_from_ground(CropType.objects.get(slug="pistachios")))

    def test_the_migration_marks_existing_rows_by_slug(self):
        walnuts = _crop("Walnuts (migration test)", "walnuts", "tree_nut", False)
        pistachios = _crop("Pistachios (migration test)", "pistachios", "tree_nut", False)
        migration = importlib.import_module("carbon.migrations.0057_crops_harvested_from_ground")
        migration.mark_crops_harvested_from_ground(django_apps, None)
        walnuts.refresh_from_db()
        pistachios.refresh_from_db()
        self.assertTrue(walnuts.harvested_from_ground)
        self.assertFalse(pistachios.harvested_from_ground)

    def test_a_crop_on_the_120_day_floor_is_not_put_to_the_certifier(self):
        avocado = _crop("Avocado (ground, 120)", "avocado_ground_review_test", "tree_fruit", True)
        avocado.harvested_from_ground = True
        self.assertFalse(gathered_from_ground(avocado))


class _Orchard(_Production):
    def setUp(self):
        super().setUp()
        self.walnuts.harvested_from_ground = True
        self.walnuts.save(update_fields=["harvested_from_ground"])
        self.applied = (timezone.now() - timedelta(days=200)).date()

    def _manure(self, history, interval="90", planned_after=None):
        return SoilManagementEvent.objects.create(
            history=history,
            created_by=self.user,
            type="OM",
            date=timezone.now() - timedelta(days=200),
            amendment_type="manure",
            manure_application_date=self.applied,
            manure_harvest_interval=interval,
            manure_harvest_date_planned=(self.applied + timedelta(days=planned_after)) if planned_after else None,
        )

    def _pick(self, history, days_after):
        return ProductionEvent.objects.create(
            history=history,
            created_by=self.user,
            type="HA",
            date=timezone.now() - timedelta(days=200 - days_after),
            description="Shaken and swept",
        )


class AReviewOnlyWhereNothingShows120DaysWereKept(_Orchard):
    def test_a_pick_100_days_after_90_day_manure_is_put_to_the_certifier(self):
        history = self._history(self.walnuts)
        app = self._manure(history)
        self._pick(history, 100)
        reviews = ground_harvest_reviews(history)
        self.assertEqual([(r.application_id, r.recorded_days, r.first_pick_days) for r in reviews], [(app.pk, 90, 100)])

    def test_a_first_pick_at_130_days_meets_both_readings(self):
        history = self._history(self.walnuts)
        self._manure(history)
        self._pick(history, 130)
        self.assertEqual(ground_harvest_reviews(history), [])

    def test_with_no_pick_the_planned_harvest_decides(self):
        history = self._history(self.walnuts)
        self._manure(history, planned_after=150)
        self.assertEqual(ground_harvest_reviews(history), [])
        other = self._history(self.walnuts)
        self._manure(other, planned_after=95)
        self.assertEqual([r.planned_days for r in ground_harvest_reviews(other)], [95])

    def test_with_no_pick_and_no_plan_it_is_put_to_the_certifier(self):
        history = self._history(self.walnuts)
        self._manure(history)
        reviews = ground_harvest_reviews(history)
        self.assertEqual([(r.first_pick_days, r.planned_days) for r in reviews], [(None, None)])

    def test_manure_under_another_season_with_no_pick_on_this_one_says_nothing(self):
        earlier = self._history(self.walnuts)
        self._manure(earlier)
        this_season = self._history(self.walnuts)
        self.assertEqual(ground_harvest_reviews(this_season), [])
        self.assertEqual(len(ground_harvest_reviews(earlier)), 1)

    def test_a_120_day_interval_or_a_crop_not_swept_from_the_ground_says_nothing(self):
        history = self._history(self.walnuts)
        self._manure(history, interval="120")
        self._pick(history, 100)
        self.assertEqual(ground_harvest_reviews(history), [])
        apples = _crop("Apples (review test)", "apples_review_test", "tree_fruit", False)
        orchard = self._history(apples)
        self._manure(orchard)
        self._pick(orchard, 100)
        self.assertEqual(ground_harvest_reviews(orchard), [])

    def test_composted_manure_meeting_the_rule_is_not_raw(self):
        history = self._history(self.walnuts)
        app = self._manure(history)
        SoilManagementEvent.objects.filter(pk=app.pk).update(
            manure_treatment="processed_5006", processed_manure_temp_f=165.0
        )
        self._pick(history, 100)
        self.assertEqual(ground_harvest_reviews(history), [])


class TheDossierNamesBothReadings(_Orchard):
    def _dossier(self, history):
        from pdfminer.high_level import extract_text

        from history.services.audit_export_service import AuditExportService

        buf = AuditExportService(history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return " ".join(extract_text(buf).split())

    def test_the_record_stays_ok_and_the_consistency_check_puts_it_to_the_certifier(self):
        history = self._history(self.walnuts)
        self._manure(history)
        self._pick(history, 100)
        text = self._dossier(history)
        self.assertIn("OK: at least 90 days", text)
        self.assertNotIn("SHORT:", text)
        self.assertIn("REVIEW: swept from the ground", text)
        self.assertIn("Raw manure interval, crop gathered from the ground", text)
        self.assertIn("The first pick after it came 100 days later.", text)
        self.assertIn("Confirm which reading your certifier applies.", text)

    def test_a_pick_at_130_days_prints_no_review(self):
        history = self._history(self.walnuts)
        self._manure(history)
        self._pick(history, 130)
        text = self._dossier(history)
        self.assertIn("OK: at least 90 days", text)
        self.assertNotIn("swept from the ground", text)
