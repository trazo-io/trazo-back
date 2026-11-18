"""The raw-manure interval is a floor, read from one place (7 CFR 205.203(c)(1)).

Found by the overall review of 2026-11 (OV-RK-C01, OV-FJ-C18, OV-FJ-C23), live in a browser:
on a freshly seeded database every crop carried `has_soil_contact=True`, because the crop
seeder never set it and migration carbon/0037 only patched the rows that existed when it ran.
The soil form then refused 90 days on apples and pears (which the rule allows) and accepted
120, and the inspector's dossier, which also matched crop names against a keyword list,
printed "MISMATCH, crop requires 90-day" beside the only answer the form had accepted. The
form also refused 120 days on any crop flagged as not touching the soil, although the rule
says "not less than" 90 days and a certifier may ask 120 of nuts swept from the orchard floor.

What these tests hold:
- one reading of the floor, `history/services/manure_interval.py`, used by the serializer,
  the model's clean(), the harvest-side check and the audit export;
- only an interval SHORTER than the crop's floor is refused or flagged;
- the seeder and data migrations put tree crops, and the seeded crops outside the tree
  categories whose edible part is held off the ground, on the 90-day floor. Each seeded crop
  is classified by name: on 2026-11-16 the category rule refused 90 days on blueberries
  ("berry", the category strawberries share) with a message saying the fruit touches the soil.
"""

import importlib
from datetime import timedelta
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production, SoilManagementEvent
from history.services.manure_interval import (
    below_minimum,
    edible_part_touches_soil,
    interval_days,
    minimum_interval_days,
)
from product.models import Parcel, Product
from users.models import User


def _crop(name, slug, category, has_soil_contact):
    return CropType.objects.create(
        name=name,
        slug=slug,
        category=category,
        description=name,
        typical_farm_size="20-100 ha",
        growing_season="perennial",
        harvest_season="fall",
        emissions_per_hectare=0.0,
        industry_average=0.0,
        best_practice=0.0,
        carbon_credit_potential=0.0,
        typical_cost_per_hectare=0.0,
        has_soil_contact=has_soil_contact,
    )


class FloorReadingTests(SimpleTestCase):
    def test_unknown_crop_gets_the_floor_that_satisfies_both_paragraphs(self):
        self.assertIsNone(edible_part_touches_soil(None))
        self.assertEqual(minimum_interval_days(None), 120)

    def test_the_flag_decides_the_floor(self):
        self.assertEqual(minimum_interval_days(SimpleNamespace(has_soil_contact=False)), 90)
        self.assertEqual(minimum_interval_days(SimpleNamespace(has_soil_contact=True)), 120)

    def test_only_a_shorter_interval_is_below_the_floor(self):
        tree = SimpleNamespace(has_soil_contact=False)
        ground = SimpleNamespace(has_soil_contact=True)
        self.assertFalse(below_minimum("90", tree))
        self.assertFalse(below_minimum("120", tree), "120 days on a tree crop is the stricter, compliant wait")
        self.assertTrue(below_minimum("90", ground))
        self.assertFalse(below_minimum("120", ground))
        self.assertFalse(below_minimum("na", ground))
        self.assertFalse(below_minimum("", ground))

    def test_legacy_suffixed_values_read_as_days(self):
        self.assertEqual(interval_days("120_days"), 120)
        self.assertIsNone(interval_days("na"))


class _Production(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="floor@test.com", password="x")
        company = Company.objects.create(name="Floor Orchards")
        establishment = Establishment.objects.create(name="Bench", company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10.0)
        self.product = Product.objects.create(name="Walnuts")
        self.walnuts = _crop("Walnuts (floor test)", "walnuts_floor_test", "tree_nut", False)
        self.lettuce = _crop("Lettuce (floor test)", "lettuce_floor_test", "vegetable", True)

    def _history(self, crop):
        return Production.objects.create(
            name=f"{crop.name} season",
            start_date=timezone.now() - timedelta(days=200),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            crop_type=crop,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )


class SavePathAcceptsAnyIntervalAtOrAboveTheFloorTests(_Production):
    def _serializer(self, history, interval):
        from history.serializers import UpdateSoilManagementEventSerializer

        return UpdateSoilManagementEventSerializer(
            data={
                "history": history.id,
                "type": "OM",
                "date": timezone.now().date().isoformat(),
                "name": "Raw manure",
                "description": "Raw manure, incorporated",
                "area_covered": "5",
                "area_unit": "ha",
                "manure_application_date": "2026-03-20",
                "manure_harvest_interval": interval,
            }
        )

    def test_a_tree_crop_takes_90_or_120_days(self):
        history = self._history(self.walnuts)
        for interval in ("90", "120"):
            serializer = self._serializer(history, interval)
            self.assertTrue(serializer.is_valid(), f"{interval} days refused: {serializer.errors}")

    def test_a_soil_contact_crop_refuses_90_days_and_says_why(self):
        history = self._history(self.lettuce)
        serializer = self._serializer(history, "90")
        self.assertFalse(serializer.is_valid())
        message = str(serializer.errors["manure_harvest_interval"])
        self.assertIn("205.203(c)(1)(ii)", message)
        self.assertIn("at least 120 days", message)
        self.assertTrue(self._serializer(history, "120").is_valid())

    def test_model_clean_reads_the_same_floor(self):
        event = SoilManagementEvent(
            history=self._history(self.walnuts),
            created_by=self.user,
            type="OM",
            date=timezone.now(),
            manure_application_date=(timezone.now() - timedelta(days=100)).date(),
            manure_harvest_interval="120",
        )
        try:
            event.clean()
        except ValidationError as exc:
            self.assertNotIn("manure_harvest_interval", exc.message_dict)


class TheActivityFormIsHeldToTheSameFloorTests(_Production):
    """VID-16 (2026-11-18): the activity form sends `parcels`, not `history`, and the season is
    found after validation, so raw manure at 90 days on carrots was saved from the form while the
    same request naming the season was refused. Both are refused now, with one message."""

    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient

        from users.models import WorksIn

        self.company = self.parcel.establishment.company
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, season, interval, **address):
        Parcel.objects.filter(pk=self.parcel.pk).update(current_history=season)
        return self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.parcel.establishment_id}/events/",
            {
                "event_type": 5,
                "type": "OM",
                "date": timezone.now().isoformat(),
                "name": "Raw manure",
                "area_covered": "5",
                "area_unit": "ha",
                "manure_treatment": "raw",
                "manure_application_date": "2026-03-20",
                "manure_harvest_interval": interval,
                **address,
            },
            format="json",
        )

    def test_the_form_cannot_record_90_days_on_a_soil_contact_crop(self):
        history = self._history(self.lettuce)
        response = self._post(history, "90", parcels=[self.parcel.pk])
        self.assertEqual(response.status_code, 400, response.content)
        message = str(response.json()["manure_harvest_interval"])
        self.assertIn("205.203(c)(1)(ii)", message)
        self.assertIn("at least 120 days", message)
        self.assertFalse(SoilManagementEvent.objects.filter(history=history).exists())

    def test_the_form_and_a_request_naming_the_season_get_the_same_refusal(self):
        history = self._history(self.lettuce)
        by_parcel = self._post(history, "90", parcels=[self.parcel.pk])
        by_season = self._post(history, "90", history=history.pk)
        self.assertEqual((by_parcel.status_code, by_season.status_code), (400, 400))
        self.assertEqual(by_parcel.json()["manure_harvest_interval"], by_season.json()["manure_harvest_interval"])

    def test_the_form_still_saves_120_days_on_a_soil_contact_crop(self):
        lettuce = self._history(self.lettuce)
        response = self._post(lettuce, "120", parcels=[self.parcel.pk])
        self.assertEqual(response.status_code, 201, response.content)

    def test_the_form_still_saves_90_or_120_days_on_a_tree_crop(self):
        walnuts = self._history(self.walnuts)
        for interval in ("90", "120"):
            response = self._post(walnuts, interval, parcels=[self.parcel.pk])
            self.assertEqual(response.status_code, 201, (interval, response.content))


class DossierReadsTheSameFloorTests(_Production):
    def _service(self, crop):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(self._history(crop), certification_type="organic")

    def test_the_crop_flag_decides_and_a_name_cannot_override_it(self):
        self.assertEqual(self._service(self.walnuts)._manure_interval_rule_for_crop()["days"], 90)
        # A tree crop a farm has deliberately put on the 120-day floor (avocados collected
        # from the ground). The name used to override the flag here and print the form's
        # accepted answer as a mismatch.
        avocado = _crop("Avocado (ground harvest)", "avocado_ground_floor_test", "tree_fruit", True)
        self.assertEqual(self._service(avocado)._manure_interval_rule_for_crop()["days"], 120)

    def _pdf_text(self, crop, interval):
        from pdfminer.high_level import extract_text

        history = self._history(crop)
        SoilManagementEvent.objects.create(
            history=history,
            created_by=self.user,
            type="OM",
            date=timezone.now() - timedelta(days=150),
            amendment_type="manure",
            manure_application_date=(timezone.now() - timedelta(days=150)).date(),
            manure_harvest_interval=interval,
        )
        from history.services.audit_export_service import AuditExportService

        buf = AuditExportService(history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return " ".join(extract_text(buf).split())

    def test_120_days_on_a_tree_crop_prints_as_meeting_the_floor(self):
        text = self._pdf_text(self.walnuts, "120")
        self.assertNotIn("MISMATCH", text)
        self.assertNotIn("SHORT:", text)
        self.assertIn("OK: at least 90 days", text)

    def test_90_days_on_a_soil_contact_crop_prints_as_short(self):
        # Written past the serializer, as a legacy or imported row would be.
        text = self._pdf_text(self.lettuce, "90")
        self.assertIn("SHORT: crop requires at least 120 days", text)


# Every seeded crop, classified by name. True: the edible part touches the soil, or can
# (§ 205.203(c)(1)(ii), 120 days). False: it is held off the ground ((c)(1)(iii), 90 days).
# A category cannot decide this ("berry" holds blueberries and strawberries), so a crop added to
# the seeder fails here until someone states its class.
SEEDED_CROP_TOUCHES_SOIL = {
    # Roots, tubers, bulbs, pods underground, leaves cut at the soil line.
    "potatoes": True,
    "carrots": True,
    "onions": True,
    "peanuts": True,
    "lettuce": True,
    "spinach": True,
    "mixed_vegetables": True,
    # Fruit lying on the soil.
    "strawberries": True,
    # Can touch the soil, so the stricter floor stays: sprawling tomatoes, the lowest soybean
    # pods, hay cured on the ground in windrows.
    "tomatoes": True,
    "soybeans": True,
    "hay_alfalfa": True,
    # Tree fruit and nuts.
    "citrus_oranges": False,
    "apples": False,
    "grapes": False,
    "avocados": False,
    "stone_fruit": False,
    "olives": False,
    "dates": False,
    "figs": False,
    "pomegranates": False,
    "pears": False,
    "walnuts": False,
    "almonds": False,
    "pecans": False,
    "hazelnuts": False,
    "pistachios": False,
    # Outside the tree categories, edible part held off the ground.
    "blueberries": False,
    "hops": False,
    "corn_field": False,
    "wheat": False,
    "rice": False,
    "sunflowers": False,
    "cotton": False,
}


class SeederAndMigrationsClassifyEachCropTests(TestCase):
    def test_every_seeded_crop_has_the_class_its_edible_part_has(self):
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        seeded = dict(CropType.objects.values_list("slug", "has_soil_contact"))
        self.assertEqual(
            set(seeded),
            set(SEEDED_CROP_TOUCHES_SOIL),
            "A seeded crop is missing from SEEDED_CROP_TOUCHES_SOIL: state whether its edible part "
            "touches the soil.",
        )
        for slug, expected in SEEDED_CROP_TOUCHES_SOIL.items():
            self.assertEqual(seeded[slug], expected, slug)

    def test_seeded_blueberries_take_90_days_and_strawberries_do_not(self):
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        self.assertEqual(minimum_interval_days(CropType.objects.get(slug="blueberries")), 90)
        self.assertEqual(minimum_interval_days(CropType.objects.get(slug="strawberries")), 120)

    def test_a_rerun_keeps_a_value_set_on_purpose(self):
        # Review of back #371: the seeder used to write the category default on every run, which
        # flipped a deliberate 120-day floor (ground-collected avocados) back to 90.
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        CropType.objects.filter(slug="avocados").update(has_soil_contact=True)
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        self.assertTrue(CropType.objects.get(slug="avocados").has_soil_contact)

    def test_the_migration_moves_existing_tree_crops_and_nothing_else(self):
        apples = _crop("Apples (migration test)", "apples_migration_test", "tree_fruit", True)
        lettuce = _crop("Lettuce (migration test)", "lettuce_migration_test", "vegetable", True)
        # The one documented decision on a tree crop (see the migration's header) is left alone.
        avocados = _crop("Avocados (migration test)", "avocados", "tree_fruit", True)
        migration = importlib.import_module("carbon.migrations.0055_tree_crops_have_no_soil_contact")
        migration.tree_crops_have_no_soil_contact(django_apps, None)
        for crop in (apples, lettuce, avocados):
            crop.refresh_from_db()
        self.assertFalse(apples.has_soil_contact)
        self.assertTrue(lettuce.has_soil_contact)
        self.assertTrue(avocados.has_soil_contact)

    def test_the_migration_moves_named_crops_held_off_the_ground_and_nothing_else(self):
        blueberries = _crop("Blueberries (migration test)", "blueberries", "berry", True)
        hops = _crop("Hops (migration test)", "hops", "other", True)
        strawberries = _crop("Strawberries (migration test)", "strawberries", "berry", True)
        soybeans = _crop("Soybeans (migration test)", "soybeans", "oilseed", True)
        migration = importlib.import_module("carbon.migrations.0056_crops_held_off_the_ground_have_no_soil_contact")
        migration.crops_held_off_the_ground_have_no_soil_contact(django_apps, None)
        for crop in (blueberries, hops, strawberries, soybeans):
            crop.refresh_from_db()
        self.assertFalse(blueberries.has_soil_contact)
        self.assertFalse(hops.has_soil_contact)
        self.assertTrue(strawberries.has_soil_contact)
        self.assertTrue(soybeans.has_soil_contact)
