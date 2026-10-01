"""
Comprehensive test suite for History app functionality.
Tests cover production events, QR code generation, and agricultural timeline management.

Test Coverage:
- Production event creation and validation
- QR code generation and scanning
- Timeline management and ordering
- Image handling and validation
- Voice event processing
- Integration with carbon calculations
- Multi-language support
- Privacy and security controls
"""

import os
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from carbon.models import CarbonEntry
from company.models import Company, Establishment
from history.models import ChemicalEvent, EquipmentEvent, History, ProductionEvent

# Skip HistoryTranslation and QRCodeData imports - models not implemented
from product.models import Parcel, Product
from subscriptions.models import Subscription
from users.models import User, WorksIn

User = get_user_model()


def _dec(value):
    """Decimal(str(x)) for test NPK values, passing None through.

    NPK are DecimalFields. Django converts a raw float with create_decimal_from_float(), which
    expands 5.2 to its exact binary value (5.2000000000000001776...) and trips the field's
    2-decimal-place validator — so float fixtures fail for reasons that have nothing to do with
    the behaviour under test. None means "this nutrient was not recorded" and must stay None.
    """
    return None if value is None else Decimal(str(value))


# Mock QRCodeData since model doesn't exist
# The `QRCodeData` mock and its `QRCodeDataTestCase` (4 tests) were removed 2026-08-11.
# The class was a test-local stub — `objects.create` was `lambda **kwargs` building an ad-hoc
# type — so the tests asserted a mock against itself and exercised no production code at all.
# One of them called `active_qr.is_expired()`, a method the mock never defined. There is no
# QRCodeData model in the codebase and never was.
#
# NOTE the real gap this exposes rather than closes: QR *generation* (`History.qr_code`,
# generate_qr_code) has no direct test. The mock created the appearance of coverage where
# there was none. Tracked as a follow-up, not fixed by deletion.


# ---------------------------------------------------------------------------
# REMOVED 2026-08-11 — six test classes written against a History model that
# does not exist and never did in this codebase.
#
#   HistoryModelTestCase (9) · HistoryViewSetTestCase (6) · HistoryAnalyticsTestCase (4)
#   HistoryIntegrationTestCase (3) · HistoryImageHandlingTestCase (3) · VoiceEventProcessingTestCase (2)
#
# They constructed History with `title`, `establishment`, `event_date`, `event_type`,
# `quantity`, `unit`, `created_by` and asserted on `history.title`, `history.event_type`,
# `history.images` — none of which are fields on History, which is a production/season
# hanging off a Parcel. They could not have passed at any point; the file also carried a
# hand-rolled mock for a QRCodeData model that has never existed. This was scaffolding
# against an imagined schema, not tests that rotted.
#
# They were deleted rather than repaired because repairing them means inventing new
# assertions against the real model — that is writing new tests, and it should be driven by
# what needs covering rather than by what a scaffold guessed. Leaving them cost more: 26
# permanent failures made the suite unreadable, which is precisely where a real 500 in
# ChemicalEvent.clean() and a falsy-zero validator bug sat undetected until 2026-08-10.
#
# COVERAGE GENUINELY LOST — these areas now have no direct test, and that is the honest
# state rather than a regression caused by this deletion (the tests never ran):
#   * History API CRUD + the role permission matrix (farmer / manager / viewer).
#     Partial cover exists in test_owner_draft_access_regression and test_public_views.
#   * Image upload size/format validation on events.
#   * Voice-event processing — a live feature (voice/AI pre-fills ~35% of fields).
#   * History analytics aggregation (per-crop, per-month, quantity rollups).
#   * QR generation (`History.qr_code`), also noted where the QRCodeData mock was removed.
# Tracked as follow-up work, not closed by deletion.
# ---------------------------------------------------------------------------


class ChemicalEventValidationTestCase(TestCase):
    """Test NPK percentage validation for ChemicalEvent model."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Validation Test Farm")

        self.establishment = Establishment.objects.create(name="Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Test Parcel", establishment=self.establishment, area=15.0)

        # Create Product instance (no establishment field)
        self.product = Product.objects.create(name="Test Avocado")

        # Create History instance that ChemicalEvents will be attached to
        self.history = History.objects.create(
            name="Test Chemical History",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_valid_npk_percentages(self):
        """Test that valid NPK percentages are accepted."""
        # Test common fertilizer ratios
        valid_combinations = [
            (20, 10, 10),  # 20-10-10 fertilizer
            (24, 8, 16),  # Miracle-Gro All Purpose
            (21, 0, 0),  # High nitrogen
            (0, 46, 0),  # Triple superphosphate
            (0, 0, 60),  # Muriate of potash
            (10.5, 5.2, 8.3),  # Decimal values
        ]

        for n, p, k in valid_combinations:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Applied Test Fertilizer {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    commercial_name=f"Test Fertilizer {n}-{p}-{k}",
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Valid NPK combination {n}-{p}-{k} was rejected")

    def test_negative_npk_percentages(self):
        """Test that negative NPK percentages are rejected."""
        negative_cases = [
            (-5, 10, 10, "nitrogen_percentage"),
            (10, -3, 10, "phosphorus_percentage"),
            (10, 10, -8, "potassium_percentage"),
        ]

        for n, p, k, expected_field in negative_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that the correct field is flagged
                self.assertIn(expected_field, context.exception.error_dict)
                self.assertIn("cannot be negative", str(context.exception))

    def test_excessive_individual_npk_percentages(self):
        """Test that individual NPK percentages over 100% are rejected."""
        excessive_cases = [
            (150, 10, 10, "nitrogen_percentage"),
            (10, 200, 10, "phosphorus_percentage"),
            (10, 10, 300, "potassium_percentage"),
        ]

        for n, p, k, expected_field in excessive_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that the correct field is flagged
                self.assertIn(expected_field, context.exception.error_dict)
                self.assertIn("cannot exceed 100%", str(context.exception))

    def test_total_npk_exceeds_100_percent(self):
        """Test that total NPK percentages exceeding 100% are rejected."""
        excessive_total_cases = [
            (60, 30, 20),  # Total = 110%
            (50, 40, 30),  # Total = 120%
            (80, 15, 10),  # Total = 105%
            (33.4, 33.4, 33.4),  # Total = 100.2%
        ]

        for n, p, k in excessive_total_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that the total is flagged
                self.assertIn("__all__", context.exception.error_dict)
                self.assertIn("Total NPK percentages cannot exceed 100%", str(context.exception))

                # Verify detailed error message includes breakdown
                error_message = str(context.exception.error_dict["__all__"][0])
                self.assertIn(f"N: {n}%", error_message)
                self.assertIn(f"P: {p}%", error_message)
                self.assertIn(f"K: {k}%", error_message)

    def test_boundary_npk_values(self):
        """Test boundary values for NPK percentages."""
        boundary_cases = [
            # Exactly at limits
            (100, 0, 0),  # Maximum nitrogen
            (0, 100, 0),  # Maximum phosphorus
            (0, 0, 100),  # Maximum potassium
            (33.33, 33.33, 33.34),  # Exactly 100%
            (0, 0, 0),  # All zeros
            # Just under limits
            (99.9, 0, 0),  # Just under max nitrogen
            (0, 99.9, 0),  # Just under max phosphorus
            (0, 0, 99.9),  # Just under max potassium
        ]

        for n, p, k in boundary_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Boundary NPK combination {n}-{p}-{k} was rejected")

    def test_partial_npk_data(self):
        """Test validation with partial NPK data (some None values)."""
        partial_cases = [
            # Only one value provided
            (25, None, None),  # Only nitrogen
            (None, 15, None),  # Only phosphorus
            (None, None, 40),  # Only potassium
            # Two values provided
            (20, 10, None),  # N and P only
            (25, None, 15),  # N and K only
            (None, 12, 30),  # P and K only
        ]

        for n, p, k in partial_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                # Should not raise ValidationError for partial data
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Partial NPK data {n}-{p}-{k} was rejected")

    def test_database_constraint_enforcement(self):
        """Test that database constraints are enforced."""
        from django.db import IntegrityError, transaction

        # Create a valid event first
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Test fertilizer for DB constraint test",
            date=timezone.now(),
            type=ChemicalEvent.FERTILIZER,
            nitrogen_percentage=20,
            phosphorus_percentage=10,
            potassium_percentage=10,
        )

        # Now try to update with invalid data directly at DB level
        # This should be caught by database constraints
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                # Try to update to invalid NPK totals
                ChemicalEvent.objects.filter(id=event.id).update(
                    nitrogen_percentage=60, phosphorus_percentage=30, potassium_percentage=20
                )

    def test_real_world_fertilizer_scenarios(self):
        """Test with real-world fertilizer NPK combinations."""
        real_fertilizers = [
            # Common commercial fertilizers
            ("Urea", 46, 0, 0),
            ("DAP", 18, 46, 0),
            ("Triple Superphosphate", 0, 46, 0),
            ("Muriate of Potash", 0, 0, 60),
            ("NPK 15-15-15", 15, 15, 15),
            ("NPK 10-26-26", 10, 26, 26),
            ("Ammonium Sulfate", 21, 0, 0),
            ("Bone Meal", 3, 15, 0),
            ("Compost", 1, 1, 1),
            ("Miracle-Gro", 24, 8, 16),
        ]

        for fertilizer_name, n, p, k in real_fertilizers:
            with self.subTest(fertilizer=fertilizer_name):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Applied {fertilizer_name}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    commercial_name=fertilizer_name,
                    # Decimal(str(x)), not the raw float: NPK are DecimalFields, and Django
                    # converts a float via create_decimal_from_float(), which expands 5.2 to its
                    # exact binary value (5.2000000000000001776...) and trips the 2-decimal-place
                    # validator. Same float-vs-Decimal hazard as the ChemicalEvent.clean() NPK
                    # total fixed 2026-08-10.
                    nitrogen_percentage=_dec(n),
                    phosphorus_percentage=_dec(p),
                    potassium_percentage=_dec(k),
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)

                    # Verify values were saved correctly
                    saved_event = ChemicalEvent.objects.get(id=event.id)
                    self.assertEqual(saved_event.nitrogen_percentage, n)
                    self.assertEqual(saved_event.phosphorus_percentage, p)
                    self.assertEqual(saved_event.potassium_percentage, k)

                except ValidationError:
                    self.fail(f"Real fertilizer {fertilizer_name} ({n}-{p}-{k}) was rejected")

    def test_application_method_validation(self):
        """Test application method structured field validation."""
        valid_methods = ["broadcast", "injection", "foliar", "drip", "banding"]

        for method in valid_methods:
            with self.subTest(method=method):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Applied fertilizer using {method} method",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=20,
                    phosphorus_percentage=10,
                    potassium_percentage=10,
                    application_method_structured=method,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertEqual(event.application_method_structured, method)
                except ValidationError:
                    self.fail(f"Valid application method {method} was rejected")

        # Test invalid method
        with self.assertRaises(ValidationError):
            event = ChemicalEvent(
                history=self.history,
                created_by=self.user,
                description="Test invalid application method",
                date=timezone.now(),
                type=ChemicalEvent.FERTILIZER,
                application_method_structured="invalid_method",
            )
            event.full_clean()


class EquipmentEventValidationTestCase(TestCase):
    """Test equipment event validation for fuel consumption and hours operated."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Equipment Test Farm")

        self.establishment = Establishment.objects.create(name="Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Test Parcel", establishment=self.establishment, area=15.0)

        # Create Product instance
        self.product = Product.objects.create(name="Test Avocado")

        # Create History instance that EquipmentEvents will be attached to
        self.history = History.objects.create(
            name="Test Equipment History",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_valid_equipment_values(self):
        """Test that valid equipment values are accepted."""
        from decimal import Decimal

        # Test common equipment scenarios
        valid_combinations = [
            # (fuel_consumed, hours_operated, equipment_type, description)
            (Decimal("20.50"), Decimal("2.50"), EquipmentEvent.FUEL_CONSUMPTION, "Small tractor plowing"),
            (Decimal("45.00"), Decimal("3.00"), EquipmentEvent.FUEL_CONSUMPTION, "Medium tractor cultivation"),
            (Decimal("100.00"), Decimal("5.00"), EquipmentEvent.FUEL_CONSUMPTION, "Large tractor harvesting"),
            (Decimal("5.50"), Decimal("1.00"), EquipmentEvent.FUEL_CONSUMPTION, "Irrigation pump operation"),
            (Decimal("0.00"), Decimal("0.00"), EquipmentEvent.MAINTENANCE, "Manual maintenance no fuel"),
            (Decimal("15.20"), Decimal("8.50"), EquipmentEvent.FUEL_CONSUMPTION, "Full day spraying"),
        ]

        for fuel, hours, event_type, description in valid_combinations:
            with self.subTest(fuel=fuel, hours=hours, type=event_type):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=description,
                    date=timezone.now(),
                    type=event_type,
                    fuel_consumed=fuel,
                    hours_operated=hours,
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Valid equipment combination {description} was rejected")

    def test_negative_fuel_consumption(self):
        """Test that negative fuel consumption is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative fuel consumption",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=-10.5,
            hours_operated=2.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that fuel_consumed field is flagged
        self.assertIn("fuel_consumed", context.exception.error_dict)
        self.assertIn("cannot be negative", str(context.exception))

    def test_negative_hours_operated(self):
        """Test that negative hours operated is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative hours operated",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=15.0,
            hours_operated=-2.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that hours_operated field is flagged
        self.assertIn("hours_operated", context.exception.error_dict)
        self.assertIn("cannot be negative", str(context.exception))

    def test_negative_maintenance_cost(self):
        """Test that negative maintenance cost is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative maintenance cost",
            date=timezone.now(),
            type=EquipmentEvent.MAINTENANCE,
            maintenance_cost=-50.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that maintenance_cost field is flagged
        self.assertIn("maintenance_cost", context.exception.error_dict)

    def test_negative_area_worked(self):
        """Test that negative area worked is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative area worked",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            area_worked=-5.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that area_worked field is flagged
        self.assertIn("area_worked", context.exception.error_dict)

    def test_excessive_hours_operated(self):
        """Test that hours operated > 1000 is rejected (max for multi-day operations)."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test excessive hours operated",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=5000.0,
            hours_operated=1200.0,  # More than 1000 hours (max for multi-day operations)
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that hours_operated field is flagged
        self.assertIn("hours_operated", context.exception.error_dict)
        self.assertIn("cannot exceed 1000 hours", str(context.exception))

    def test_fuel_without_hours_validation(self):
        """Test validation when fuel is provided without hours."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test fuel without hours",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=25.0,
            hours_operated=None,  # Missing hours
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that hours_operated field is flagged
        self.assertIn("hours_operated", context.exception.error_dict)
        self.assertIn("should be provided when fuel consumption is recorded", str(context.exception))

    def test_unreasonable_fuel_efficiency_high(self):
        """Test detection of unreasonably high fuel consumption."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test unreasonably high fuel consumption",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=200.0,  # 200L in 2 hours = 100L/hr (unreasonable)
            hours_operated=2.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that fuel_consumed field is flagged for high consumption
        self.assertIn("fuel_consumed", context.exception.error_dict)
        self.assertIn("unreasonably high", str(context.exception))

    def test_unreasonable_fuel_efficiency_low(self):
        """Test detection of unreasonably low fuel consumption."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test unreasonably low fuel consumption",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=0.2,  # 0.2L in 10 hours = 0.02L/hr (unreasonable)
            hours_operated=10.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that fuel_consumed field is flagged for low consumption
        self.assertIn("fuel_consumed", context.exception.error_dict)
        self.assertIn("unreasonably low", str(context.exception))

    def test_boundary_values(self):
        """Test boundary values for equipment validation."""
        from decimal import Decimal

        boundary_cases = [
            # Exactly at limits
            (Decimal("0.00"), Decimal("0.00")),  # Zero values (allowed)
            (Decimal("30.00"), Decimal("24.00")),  # Reasonable day consumption
            (Decimal("24.00"), Decimal("24.00")),  # 1L/hr (reasonable)
            (Decimal("600.00"), Decimal("12.00")),  # 50L/hr (maximum reasonable)
            # Just under limits
            (Decimal("23.90"), Decimal("23.90")),  # Just under max hours
            (Decimal("3.00"), Decimal("1.00")),  # 3L/hr (reasonable small tractor)
            (Decimal("49.00"), Decimal("1.00")),  # Just under max efficiency
        ]

        for fuel, hours in boundary_cases:
            with self.subTest(fuel=fuel, hours=hours):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test boundary fuel={fuel}L, hours={hours}h",
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    fuel_consumed=fuel,
                    hours_operated=hours,
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Boundary case fuel={fuel}L, hours={hours}h was rejected")

    def test_real_world_equipment_scenarios(self):
        """Test with real-world equipment scenarios."""
        real_scenarios = [
            # (fuel, hours, equipment_type, description)
            (8.5, 1.5, "tractor_small", "Small tractor plowing 2 hectares"),
            (45.0, 3.0, "tractor_medium", "Medium tractor cultivating"),
            (120.0, 4.0, "tractor_large", "Large tractor with heavy implements"),
            (15.0, 6.0, "irrigation_pump", "Irrigation pump watering crops"),
            (80.0, 2.5, "harvester", "Combine harvester collecting grain"),
            (25.0, 3.5, "sprayer", "Field sprayer applying chemicals"),
            (35.0, 4.0, "cultivator", "Cultivator preparing seedbed"),
            (60.0, 5.0, "transport", "Transport vehicle moving produce"),
        ]

        for fuel, hours, equipment_type, description in real_scenarios:
            with self.subTest(scenario=description):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=description,
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    fuel_consumed=fuel,
                    hours_operated=hours,
                    equipment_type_structured=equipment_type,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)

                    # Verify values were saved correctly
                    saved_event = EquipmentEvent.objects.get(id=event.id)
                    self.assertEqual(saved_event.fuel_consumed, fuel)
                    self.assertEqual(saved_event.hours_operated, hours)
                    self.assertEqual(saved_event.equipment_type_structured, equipment_type)

                except ValidationError:
                    self.fail(f"Real equipment scenario {description} was rejected")

    def test_database_constraint_enforcement(self):
        """Test that database constraints are enforced."""
        from django.db import IntegrityError, transaction

        # Create a valid event first
        event = EquipmentEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Test equipment for DB constraint test",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=25.0,
            hours_operated=5.0,
        )

        # Now try to update with invalid data directly at DB level
        # This should be caught by database constraints
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                # Try to update to invalid negative fuel consumption
                EquipmentEvent.objects.filter(id=event.id).update(fuel_consumed=-10.0)

    def test_equipment_type_validation(self):
        """Test equipment type structured field validation."""
        valid_types = [
            "tractor_small",
            "tractor_medium",
            "tractor_large",
            "irrigation_pump",
            "harvester",
            "sprayer",
            "cultivator",
            "transport",
        ]

        for equipment_type in valid_types:
            with self.subTest(type=equipment_type):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test {equipment_type} equipment",
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    fuel_consumed=20.0,
                    hours_operated=4.0,
                    equipment_type_structured=equipment_type,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertEqual(event.equipment_type_structured, equipment_type)
                except ValidationError:
                    self.fail(f"Valid equipment type {equipment_type} was rejected")

    def test_maintenance_event_no_fuel(self):
        """Test maintenance events without fuel consumption."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Regular maintenance checkup",
            date=timezone.now(),
            type=EquipmentEvent.MAINTENANCE,
            maintenance_cost=150.0,
            fuel_consumed=None,  # No fuel consumed during maintenance
            hours_operated=2.0,  # Hours spent on maintenance
        )

        # Should not raise ValidationError
        try:
            event.full_clean()
            event.save()
            self.assertIsNotNone(event.id)
            self.assertIsNone(event.fuel_consumed)
            self.assertEqual(event.maintenance_cost, 150.0)
        except ValidationError:
            self.fail("Maintenance event without fuel consumption was rejected")

    def test_partial_equipment_data(self):
        """Test validation with partial equipment data (some None values)."""
        partial_cases = [
            # Only fuel_consumed provided
            {"fuel_consumed": 25.0, "hours_operated": None, "area_worked": None},
            # Only hours_operated provided
            {"fuel_consumed": None, "hours_operated": 3.0, "area_worked": None},
            # Only area_worked provided
            {"fuel_consumed": None, "hours_operated": None, "area_worked": 5.0},
            # Two values provided
            {"fuel_consumed": None, "hours_operated": 2.0, "area_worked": 3.0},
        ]

        for case_data in partial_cases:
            with self.subTest(data=case_data):
                # Note: fuel without hours should trigger validation error
                should_error = (
                    case_data.get("fuel_consumed")
                    and case_data.get("fuel_consumed") > 0
                    and not case_data.get("hours_operated")
                )

                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test partial data: {case_data}",
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    **case_data,
                )

                if should_error:
                    with self.assertRaises(ValidationError):
                        event.full_clean()
                else:
                    try:
                        event.full_clean()
                        event.save()
                        self.assertIsNotNone(event.id)
                    except ValidationError:
                        self.fail(f"Partial equipment data {case_data} was rejected")


# Production Event Validation Tests
class ProductionEventValidationTestCase(TestCase):
    """Test production event validation for area, yield, and transportation constraints."""

    def setUp(self):
        """Set up test data for production event validation tests."""
        # Create test user
        self.user = User.objects.create_user(email="testuser@example.com", password="testpass123")

        # Create test company and establishment
        self.company = Company.objects.create(
            name="Test Organic Farm",
            contact_email="test@farm.com",
            city="Test City",
            state="Test State",
            address="123 Test Street",
        )

        # Create test plan and subscription
        from subscriptions.models import Plan

        self.plan = Plan.objects.create(
            name="Basic Plan",
            slug="basic",
            description="Basic plan for testing",
            price=29.99,  # Add required price field
        )

        self.subscription = Subscription.objects.create(
            company=self.company, plan=self.plan, stripe_subscription_id="test_sub_123"
        )

        # Create test establishment
        self.establishment = Establishment.objects.create(name="Main Farm Location", company=self.company)

        # Link user to company
        self.works_in = WorksIn.objects.create(user=self.user, company=self.company)
        self.works_in.establishments_in_charge.add(self.establishment)

        # Create test parcel and product
        self.parcel = Parcel.objects.create(name="Test Field A", establishment=self.establishment, area=10.5)

        # Product has no `company` field, and `parcel` is a reverse relation from Parcel —
        # not a constructor kwarg. Only setUp was stale here; the tests in this class assert
        # on ProductionEvent.area_covered / yield_quantity, which are current fields.
        self.product = Product.objects.create(name="Organic Avocados")

        # Create test history for events
        self.history = History.objects.create(
            # History's owner field is `operator`, not `user`.
            operator=self.user,
            product=self.product,
            parcel=self.parcel,
            name="Test Production History",
            # History.save() formats start_date, so omitting it raises
            # AttributeError: 'NoneType' object has no attribute 'strftime'.
            start_date=timezone.now() - timedelta(days=30),
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_valid_production_values(self):
        """Test that valid production values are accepted."""
        from decimal import Decimal

        # Test common production scenarios
        valid_combinations = [
            # (area_covered, yield_quantity, transportation_distance, equipment_hours, description)
            (Decimal("2.50"), Decimal("5000.00"), Decimal("25.00"), Decimal("4.00"), "Small field harvesting"),
            (Decimal("10.00"), Decimal("15000.00"), Decimal("50.00"), Decimal("8.00"), "Medium farm planting"),
            (Decimal("0.10"), Decimal("100.00"), Decimal("5.00"), Decimal("1.00"), "Small plot test"),
            (Decimal("50.00"), Decimal("75000.00"), Decimal("100.00"), Decimal("12.00"), "Large field operation"),
            (Decimal("1.00"), None, Decimal("0.00"), Decimal("2.00"), "Planting with no yield yet"),
            (Decimal("5.00"), Decimal("0.00"), Decimal("15.00"), None, "Field preparation"),
        ]

        for area, yield_qty, transport_dist, equip_hours, description in valid_combinations:
            with self.subTest(area=area, yield_qty=yield_qty, transport=transport_dist, hours=equip_hours):
                event = ProductionEvent(
                    history=self.history,
                    created_by=self.user,
                    type=ProductionEvent.HARVESTING,
                    description=description,
                    date=timezone.now(),
                    area_covered=area,
                    yield_quantity=yield_qty,
                    transportation_distance=transport_dist,
                    equipment_hours=equip_hours,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertTrue(True, f"Valid production combination {description} was accepted")
                except ValidationError as e:
                    self.fail(f"Valid production combination {description} was rejected: {e}")

    def test_invalid_area_covered(self):
        """Test that invalid area covered values are rejected."""
        from decimal import Decimal

        invalid_areas = [
            (Decimal("-1.00"), "Negative area"),
            (Decimal("0.00"), "Zero area"),
        ]

        for invalid_area, description in invalid_areas:
            with self.subTest(area=invalid_area):
                event = ProductionEvent(
                    history=self.history,
                    created_by=self.user,
                    type=ProductionEvent.PLANTING,
                    description=f"Test {description}",
                    date=timezone.now(),
                    area_covered=invalid_area,
                    yield_quantity=Decimal("1000.00"),
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that area_covered field is flagged
                self.assertIn("area_covered", context.exception.error_dict)

    def test_invalid_yield_quantity(self):
        """Test that negative yield quantities are rejected."""
        from decimal import Decimal

        event = ProductionEvent(
            history=self.history,
            created_by=self.user,
            type=ProductionEvent.HARVESTING,
            description="Test negative yield",
            date=timezone.now(),
            area_covered=Decimal("5.00"),
            yield_quantity=Decimal("-100.00"),
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that yield_quantity field is flagged
        self.assertIn("yield_quantity", context.exception.error_dict)

    def test_real_world_production_scenarios(self):
        """Test with real-world production scenarios."""
        from decimal import Decimal

        real_scenarios = [
            (
                Decimal("5.0"),
                Decimal("25000.0"),
                Decimal("30.0"),
                Decimal("6.0"),
                "avocado",
                "Avocado harvest - 5 tons/ha",
            ),
            (
                Decimal("2.5"),
                Decimal("7500.0"),
                Decimal("15.0"),
                Decimal("4.0"),
                "citrus",
                "Citrus harvest - 3 tons/ha",
            ),
            (Decimal("10.0"), None, Decimal("50.0"), Decimal("8.0"), "planting", "Field planting - no yield yet"),
            (
                Decimal("1.0"),
                Decimal("4000.0"),
                Decimal("10.0"),
                Decimal("2.0"),
                "vegetable",
                "Vegetable harvest - 4 tons/ha",
            ),
            (
                Decimal("20.0"),
                Decimal("120000.0"),
                Decimal("75.0"),
                Decimal("12.0"),
                "grain",
                "Grain harvest - 6 tons/ha",
            ),
        ]

        for area, yield_qty, transport, hours, crop_type, description in real_scenarios:
            with self.subTest(crop=crop_type, desc=description):
                event = ProductionEvent(
                    history=self.history,
                    created_by=self.user,
                    type=ProductionEvent.HARVESTING if yield_qty else ProductionEvent.PLANTING,
                    description=description,
                    date=timezone.now(),
                    area_covered=area,
                    yield_quantity=yield_qty,
                    transportation_distance=transport,
                    equipment_hours=hours,
                )

                try:
                    event.full_clean()
                    event.save()
                    # Verify carbon calculation integration
                    self.assertIsNotNone(event.id)
                except ValidationError as e:
                    self.fail(f"Real-world scenario {description} failed: {e}")
