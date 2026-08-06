"""
NOP validator tests — Sprint 1 implementation (2026-04-13).

Covers:
- NOP 5029 / 7 CFR 205.204(a)(1): Non-organic seed requires >=3 supplier search attempts
- NOP 7 CFR 205.203(c)(1): Raw manure harvest-interval block (90/120 day)
- Compost exception (>=131F + 5 turnings) bypasses the manure validator
- skip_manure_validation=True bypass for historical data imports
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import History, ProductionEvent, SoilManagementEvent
from product.models import Parcel, Product
from users.models import User


class NOPSeedSearchValidatorTests(TestCase):
    """NOP 5029 / 7 CFR 205.204(a)(1) — seed commercial-availability search."""

    def setUp(self):
        self.user = User.objects.create_user(email="seed@test.com", password="x")
        self.company = Company.objects.create(name="Seed Farm")
        self.establishment = Establishment.objects.create(name="Field A", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Tomato")
        self.history = History.objects.create(
            name="H1",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _planting_event(self, **overrides):
        defaults = dict(
            history=self.history,
            created_by=self.user,
            description="Planted beefsteak tomatoes",
            date=timezone.now(),
            type="PL",
            area_covered=1.0,
        )
        defaults.update(overrides)
        return ProductionEvent(**defaults)

    def test_non_organic_seed_without_search_is_rejected(self):
        event = self._planting_event(seed_certification_status="non_organic_untreated", seed_search_attempts=[])
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("seed_search_attempts", ctx.exception.message_dict)

    def test_non_organic_seed_with_two_attempts_still_rejected(self):
        event = self._planting_event(
            seed_certification_status="non_organic_treated",
            seed_search_attempts=[
                {"supplier_name": "A", "date_contacted": "2026-01-01", "result": "none"},
                {"supplier_name": "B", "date_contacted": "2026-01-02", "result": "none"},
            ],
        )
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_non_organic_seed_with_three_attempts_is_valid(self):
        event = self._planting_event(
            seed_certification_status="non_organic_untreated",
            seed_search_attempts=[
                {"supplier_name": "A", "date_contacted": "2026-01-01", "result": "none"},
                {"supplier_name": "B", "date_contacted": "2026-01-02", "result": "none"},
                {"supplier_name": "C", "date_contacted": "2026-01-03", "result": "none"},
            ],
        )
        event.full_clean()  # should not raise

    def test_certified_organic_seed_never_requires_search(self):
        event = self._planting_event(seed_certification_status="certified_organic", seed_search_attempts=[])
        event.full_clean()  # should not raise


class NOPManureHarvestIntervalTests(TestCase):
    """NOP 7 CFR 205.203(c)(1) — raw manure harvest-interval block."""

    def setUp(self):
        self.user = User.objects.create_user(email="manure@test.com", password="x")
        self.company = Company.objects.create(name="Manure Farm")
        self.establishment = Establishment.objects.create(name="Field B", company=self.company)
        self.parcel = Parcel.objects.create(name="P2", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Romaine")

        # Soil-contact crop -> 120-day window
        self.leafy_crop = CropType.objects.create(
            name="Romaine Lettuce",
            slug="romaine_lettuce",
            category="vegetable",
            description="Leafy green",
            typical_farm_size="5-20 ha",
            growing_season="60 days",
            harvest_season="year-round",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        # No-soil-contact crop -> 90-day window
        self.tree_crop = CropType.objects.create(
            name="Hass Avocado",
            slug="hass_avocado",
            category="tree_fruit",
            description="Tree fruit",
            typical_farm_size="20-100 ha",
            growing_season="evergreen",
            harvest_season="year-round",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=False,
        )

        self.history = History.objects.create(
            name="Leafy history",
            start_date=timezone.now() - timedelta(days=200),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            crop_type=self.leafy_crop,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _apply_raw_manure(self, days_ago, exempt=False):
        """Create a SoilManagementEvent with a manure application date `days_ago` in the past."""
        application_date = (timezone.now() - timedelta(days=days_ago)).date()
        kwargs = dict(
            history=self.history,
            created_by=self.user,
            description="Raw manure application",
            date=timezone.now() - timedelta(days=days_ago),
            type="CO",  # composting/organic amendment subtype
            manure_application_date=application_date,
            manure_harvest_interval="120",
        )
        if exempt:
            # Full § 205.203(c)(2) compliance: C:N 25–40 + 131–170°F + windrow 15d/5 turns.
            kwargs["compost_peak_temp_f"] = 140
            kwargs["compost_turning_count"] = 5
            kwargs["compost_duration_days_at_temp"] = 20
            kwargs["compost_method"] = "windrow"
            kwargs["compost_initial_cn_ratio"] = 30
        return SoilManagementEvent.objects.create(**kwargs)

    def _harvest_event(self, days_from_now=0):
        return ProductionEvent(
            history=self.history,
            created_by=self.user,
            description="Harvest",
            date=timezone.now() + timedelta(days=days_from_now),
            type="HA",
            area_covered=1.0,
            yield_quantity=100.0,
        )

    def test_harvest_inside_120_day_window_is_blocked(self):
        self._apply_raw_manure(days_ago=60)  # leafy -> 120-day window
        event = self._harvest_event(days_from_now=0)
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("date", ctx.exception.message_dict)
        self.assertIn("120-day", str(ctx.exception))

    def test_harvest_after_120_day_window_is_allowed(self):
        self._apply_raw_manure(days_ago=130)
        event = self._harvest_event(days_from_now=0)
        event.full_clean()  # should not raise

    def test_qualifying_compost_bypasses_the_block(self):
        # 60 days ago, but the event meets 205.203(c)(2) compost exception.
        self._apply_raw_manure(days_ago=60, exempt=True)
        event = self._harvest_event(days_from_now=0)
        event.full_clean()  # should not raise

    def test_data_import_bypass_downgrades_block(self):
        self._apply_raw_manure(days_ago=30)
        event = self._harvest_event(days_from_now=0)
        event.skip_manure_validation = True
        event.full_clean()  # should not raise even though inside window

    def test_compost_with_cn_out_of_range_does_not_bypass(self):
        # Pile has temp + turnings + duration + method but C:N = 18:1 (out of 25-40).
        # § 205.203(c)(2) is NOT satisfied → must be treated as raw manure (c)(1).
        from history.models import SoilManagementEvent

        SoilManagementEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Low-C:N pile",
            date=timezone.now() - timedelta(days=60),
            type="CO",
            manure_application_date=(timezone.now() - timedelta(days=60)).date(),
            manure_harvest_interval="120",
            compost_peak_temp_f=140,
            compost_turning_count=5,
            compost_duration_days_at_temp=20,
            compost_method="windrow",
            compost_initial_cn_ratio=18,
        )
        event = self._harvest_event(days_from_now=0)
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_documented_processed_5006_manure_bypasses_the_block(self):
        # NOP 5006: manure processed to reduce pathogens is interval-exempt when
        # documented. 60 days ago (inside the 120-day raw window) but processed
        # with a recorded processing temperature → harvest must NOT be blocked.
        SoilManagementEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Processed poultry pellets",
            date=timezone.now() - timedelta(days=60),
            type="CO",
            manure_application_date=(timezone.now() - timedelta(days=60)).date(),
            manure_treatment="processed_5006",
            processed_manure_temp_f=150,
        )
        event = self._harvest_event(days_from_now=0)
        event.full_clean()  # should not raise — NOP 5006 exemption

    def test_processed_5006_manure_bypasses_via_attestation(self):
        # Exemption is also granted when only an OMRI/supplier attestation is on file.
        SoilManagementEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Processed manure via attestation",
            date=timezone.now() - timedelta(days=60),
            type="CO",
            manure_application_date=(timezone.now() - timedelta(days=60)).date(),
            manure_treatment="processed_5006",
            processed_manure_attestation="OMRI-listed heat-processed poultry pellets, PFRP",
        )
        event = self._harvest_event(days_from_now=0)
        event.full_clean()  # should not raise

    def test_undocumented_processed_5006_manure_does_not_bypass(self):
        # Classified processed_5006 but NO temperature and NO attestation → the
        # exemption is not earned; the event reverts to the raw (c)(1) interval.
        SoilManagementEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Undocumented 'processed' manure",
            date=timezone.now() - timedelta(days=60),
            type="CO",
            manure_application_date=(timezone.now() - timedelta(days=60)).date(),
            manure_harvest_interval="120",
            manure_treatment="processed_5006",
        )
        event = self._harvest_event(days_from_now=0)
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_processed_5006_with_raw_interval_is_rejected_at_clean(self):
        # An event cannot be both processed-exempt AND carry a raw 90/120 interval.
        ev = SoilManagementEvent(
            history=self.history,
            created_by=self.user,
            description="Contradictory manure classification",
            date=timezone.now(),
            type="OM",
            manure_application_date=timezone.now().date(),
            manure_treatment="processed_5006",
            processed_manure_temp_f=150,
            manure_harvest_interval="120",  # raw interval — contradiction
        )
        with self.assertRaises(ValidationError) as ctx:
            ev.full_clean()
        self.assertIn("manure_harvest_interval", ctx.exception.message_dict)

    def test_processed_5006_without_documentation_is_rejected_at_clean(self):
        # Claiming the NOP 5006 exemption requires temperature or attestation.
        ev = SoilManagementEvent(
            history=self.history,
            created_by=self.user,
            description="Undocumented processed manure",
            date=timezone.now(),
            type="OM",
            manure_application_date=timezone.now().date(),
            manure_treatment="processed_5006",  # no temp, no attestation
        )
        with self.assertRaises(ValidationError) as ctx:
            ev.full_clean()
        self.assertIn("manure_treatment", ctx.exception.message_dict)

    def test_compost_missing_method_does_not_bypass(self):
        # Temp + duration + C:N present but no method — cannot assert (c)(2) path.
        from history.models import SoilManagementEvent

        SoilManagementEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Method-missing pile",
            date=timezone.now() - timedelta(days=60),
            type="CO",
            manure_application_date=(timezone.now() - timedelta(days=60)).date(),
            manure_harvest_interval="120",
            compost_peak_temp_f=140,
            compost_turning_count=5,
            compost_duration_days_at_temp=20,
            compost_initial_cn_ratio=30,
        )
        event = self._harvest_event(days_from_now=0)
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_static_aerated_3_day_path_bypasses(self):
        # Static aerated pile: 3 days at temp is the full (c)(2) requirement, no turnings required.
        from history.models import SoilManagementEvent

        SoilManagementEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Static aerated pile",
            date=timezone.now() - timedelta(days=60),
            type="CO",
            manure_application_date=(timezone.now() - timedelta(days=60)).date(),
            manure_harvest_interval="120",
            compost_peak_temp_f=140,
            compost_duration_days_at_temp=5,
            compost_method="static_aerated",
            compost_initial_cn_ratio=30,
        )
        event = self._harvest_event(days_from_now=0)
        event.full_clean()  # should not raise

    def test_tree_fruit_uses_90_day_window(self):
        # Re-point history at tree crop.
        self.history.crop_type = self.tree_crop
        self.history.save()
        # 95 days ago with tree fruit -> allowed (90-day window).
        self._apply_raw_manure(days_ago=95)
        event = self._harvest_event(days_from_now=0)
        event.full_clean()  # should not raise

        # 60 days ago with tree fruit -> blocked (still inside 90-day window).
        SoilManagementEvent.objects.all().delete()
        self._apply_raw_manure(days_ago=60)
        event = self._harvest_event(days_from_now=0)
        with self.assertRaises(ValidationError):
            event.full_clean()
