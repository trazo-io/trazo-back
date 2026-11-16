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
- the seeder and a data migration put tree crops on the 90-day floor.
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


class SeederAndMigrationPutTreeCropsOnTheNinetyDayFloorTests(TestCase):
    def test_the_seeder_sets_the_flag_from_the_category(self):
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        seeded = CropType.objects.all()
        self.assertTrue(seeded.filter(category__in=CropType.NO_SOIL_CONTACT_CATEGORIES).exists())
        for crop in seeded:
            expected = crop.category not in CropType.NO_SOIL_CONTACT_CATEGORIES
            self.assertEqual(crop.has_soil_contact, expected, f"{crop.name} ({crop.category})")

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
