"""Zero is a value the operator entered. Missing is the absence of one.

Conflating the two is how this codebase invents carbon. Found 2026-08-20 while sweeping
every activity that produces emissions:

    _convert_area_to_hectares(Decimal("0"))  ->  0.404686 ha   (one acre)
    _convert_area_to_hectares("0")           ->  1.0 ha        (one hectare)

`SoilManagementEvent.area_covered` is a Decimal, and `Decimal("0")` is falsy, so
`float(area_str) if area_str else 1.0` read an explicit zero as "not supplied" and
substituted a default. A tillage record with zero area reported **151.2 kg CO2e** — a
number with no input behind it, rendered in the wizard and printed into the certifier
packet like any other. The caller compounded it: `getattr(event, "area_covered", None) or
getattr(event, "area", "0")` turned Decimal("0") into the string "0", which then hit the
1-hectare "intelligent default".

The rule these tests pin: a supplied zero produces zero. Only None/""/"unknown" — the
operator genuinely not telling us — may fall back to a default.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from carbon.services.event_carbon_calculator import EventCarbonCalculator


class _AreaEvent:
    """Minimal event carrying only what the area converter reads."""

    def __init__(self, area_unit="acres", **kwargs):
        self.area_unit = area_unit
        for key, value in kwargs.items():
            setattr(self, key, value)


class AreaZeroVersusMissingTests(SimpleTestCase):
    def setUp(self):
        self.calculator = EventCarbonCalculator()
        self.event = _AreaEvent()

    def test_explicit_zero_converts_to_zero_in_every_supported_type(self):
        """Decimal, int, float and str all reach this function from different call sites."""
        for supplied in (Decimal("0"), 0, 0.0, "0", "0 acres"):
            with self.subTest(supplied=repr(supplied)):
                self.assertEqual(
                    self.calculator._convert_area_to_hectares(supplied, event=self.event),
                    0.0,
                    f"{supplied!r} is a reported zero, not a missing value",
                )

    def test_genuinely_missing_area_still_falls_back(self):
        """The default exists for real gaps; removing it entirely would under-report."""
        for supplied in (None, "", "unknown"):
            with self.subTest(supplied=repr(supplied)):
                self.assertGreater(
                    self.calculator._convert_area_to_hectares(supplied, event=self.event),
                    0.0,
                    f"{supplied!r} means the operator told us nothing — a default is appropriate",
                )

    def test_real_area_still_converts_by_unit(self):
        """Guard against 'fix zero, break everything else'."""
        self.assertAlmostEqual(
            self.calculator._convert_area_to_hectares(Decimal("0.6"), event=_AreaEvent("acres")),
            0.6 * 0.404686,
            places=6,
        )
        self.assertAlmostEqual(
            self.calculator._convert_area_to_hectares(Decimal("5"), event=_AreaEvent("ha")),
            5.0,
            places=6,
        )

    def test_zero_area_soil_event_reports_zero_not_a_default_hectare(self):
        """End-to-end: the tillage case that reported 151.2 kg from nothing."""

        class _SoilEvent:
            id = 1
            history = None
            extra_data: dict = {}
            type = "TI"
            area_covered = Decimal("0")
            area_unit = "acres"
            fuel_consumed = None
            fuel_unit = "gal"
            fuel_type = "diesel"
            equipment_hours = None
            volume = None
            observation = ""

        result = self.calculator.calculate_soil_management_event_impact(_SoilEvent())
        self.assertEqual(
            float(result["co2e"]),
            0.0,
            "zero area must not be inflated to the 1-hectare default",
        )


from django.test import TestCase  # noqa: E402
from django.utils import timezone  # noqa: E402


class Run8UnreportedIsNotEstimatedTests(TestCase):
    """Run 8 (R8-04, Astra 2026-10-05): a post-harvest cleanout saved with no fuel showed 129 kg CO2e
    and an EPA/USDA badge while its edit preview showed 0. The saved path borrowed the parcel's
    area and charged a per-hectare diesel estimate on it. Rule (Oscar's amendment): unknown is
    not zero and not a guess. Each test was red against the code before the change."""

    def setUp(self):
        from company.models import Company, Establishment
        from history.models import Production
        from product.models import Parcel, Product
        from users.models import User

        user = User.objects.create_user(email="r8carbon@test.com", password="x")
        est = Establishment.objects.create(name="R8C", company=Company.objects.create(name="R8C Co"), state="OR")
        self.history = Production.objects.create(
            name="Duke 2026",
            start_date=timezone.now(),
            product=Product.objects.create(name="Blueberries"),
            parcel=Parcel.objects.create(name="Home Field East", establishment=est, area=5.06),
            operator=user,
        )

    def _event(self, subtype, **kw):
        from history.models import ProductionEvent

        event = ProductionEvent.objects.create(history=self.history, type=subtype, date=timezone.now(), **kw)
        event.refresh_from_db()
        return event

    def _entries(self, event):
        from carbon.models import CarbonEntry

        return CarbonEntry.objects.filter(
            production=self.history, description__icontains=f"ProductionEvent(ID={event.id})"
        )

    def _served(self, event):
        from history.serializers import ProductionEventSerializer

        return ProductionEventSerializer(event).data["carbon_data"]

    def test_a_zero_computed_from_reported_inputs_is_stored_and_served(self):
        """Review of back #123: a reported input that computes to zero (an electric line on
        solar, a fuel recorded in a unit that converts to nothing) is an answer. It must keep
        its entry and card, not vanish with neither an entry nor a not-estimated status."""
        from unittest.mock import patch

        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        zero = {"co2e": 0.0, "efficiency_score": 0, "calculation_method": "verified_epa_usda_factors"}
        with patch.object(EventCarbonCalculator, "calculate_production_event_impact", return_value=zero):
            event = self._event("EM", fuel_consumed=4.0)
        self.assertEqual(self._entries(event).count(), 1, "a reported zero was dropped")
        served = self._served(event)
        self.assertIsNotNone(served, "the card vanished for a reported zero")
        self.assertNotEqual(served.get("calculation_method"), "not_estimated")

    def test_a_cleanout_with_no_fuel_stores_nothing_and_says_not_estimated(self):
        event = self._event("EM", description="Post-harvest cleanout of bins and sprayer lines")
        self.assertFalse(self._entries(event).exists())
        served = self._served(event)
        self.assertIsNotNone(served, "no carbon status served: the event says nothing at all")
        self.assertIsNone(served["co2e"])
        self.assertEqual(served["calculation_method"], "not_estimated")
        self.assertFalse(served["usda_factors_based"])

    def test_a_cleanout_with_reported_fuel_is_counted(self):
        event = self._event("EM", fuel_consumed=3, fuel_unit="gal", fuel_type="diesel")
        self.assertTrue(self._entries(event).exists())
        self.assertGreater(self._served(event)["co2e"], 0)

    def test_field_work_with_no_area_on_the_record_never_borrows_the_parcel(self):
        for subtype in ("FP", "MO"):
            with self.subTest(subtype=subtype):
                event = self._event(subtype)
                self.assertFalse(self._entries(event).exists())
                served = self._served(event)
                self.assertIsNotNone(served, "no carbon status served: the event says nothing at all")
                self.assertIsNone(served["co2e"])
                self.assertEqual(served["calculation_method"], "not_estimated")

    def test_an_area_estimate_is_labelled_as_one_and_carries_no_epa_badge(self):
        event = self._event("MO", area_covered=4.0, area_unit="acres")
        entry = self._entries(event).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.verification_status, "area_estimate")
        served = self._served(event)
        self.assertGreater(served["co2e"], 0)
        self.assertFalse(served["usda_factors_based"])
        self.assertEqual(served["verification_status"], "area_estimate")

    def test_the_preview_matches_what_the_save_stores(self):
        from carbon.views import OptimizedCarbonCalculator

        preview = OptimizedCarbonCalculator().calculate_production_impact_optimized(
            {"production_type": "EM", "area_covered": 0.0, "fuel_consumed": None, "fuel_type": "diesel"}
        )
        self.assertIsNone(preview["co2e"])
        self.assertTrue(preview["not_estimated"])


class Run8RecomputeCommandTests(Run8UnreportedIsNotEstimatedTests):
    """recompute_unreported_carbon follows the production safety rule: dry run, apply, idempotent
    re-run, restore with every deleted row back."""

    # Run only the command test here, not the inherited ones.
    test_a_cleanout_with_no_fuel_stores_nothing_and_says_not_estimated = None
    test_a_cleanout_with_reported_fuel_is_counted = None
    test_field_work_with_no_area_on_the_record_never_borrows_the_parcel = None
    test_an_area_estimate_is_labelled_as_one_and_carries_no_epa_badge = None
    test_the_preview_matches_what_the_save_stores = None

    def test_dry_run_apply_rerun_and_restore(self):
        import io
        import json
        import os
        import tempfile
        from pathlib import Path

        from django.core.management import call_command

        from carbon.models import CarbonEntry
        from common.models import DataOperationLog
        from history.models import ProductionEvent

        event = self._event("EM", description="Cleanout")
        # A record saved under the old rule: no status on the event, and a per-hectare guess on
        # the parcel's area stored as its figure.
        ProductionEvent.objects.filter(pk=event.pk).update(extra_data={})
        old = CarbonEntry.objects.create(
            production=self.history,
            type="emission",
            amount=129.0,
            co2e_amount=129.0,
            year=2026,
            description=f"Auto-calculated from ProductionEvent(ID={event.id}) event: usda_standard_per_hectare",
            usda_factors_based=True,
            verification_status="factors_verified",
        )

        def run(path, *flags):
            args = ["recompute_unreported_carbon", *flags]
            if "--restore" not in flags:
                args += ["--report", path]
            call_command(*args, stdout=io.StringIO())

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "carbon.json")
            run(path)
            self.assertTrue(CarbonEntry.objects.filter(pk=old.pk).exists(), "a dry run saved")
            report = json.loads(Path(path).read_text())
            self.assertEqual([c["pk"] for c in report["changes"]], [event.pk])

            run(path, "--apply")
            self.assertFalse(CarbonEntry.objects.filter(pk=old.pk).exists())
            event.refresh_from_db()
            self.assertEqual(event.extra_data["carbon_calculation"]["calculation_method"], "not_estimated")
            self.assertTrue(DataOperationLog.objects.filter(action="apply").exists())

            again = os.path.join(tmp, "again.json")
            run(again)
            self.assertEqual(json.loads(Path(again).read_text())["changes"], [], "not idempotent")

            run(path, "--restore", path)
            restored = CarbonEntry.objects.get(pk=old.pk)
            self.assertEqual(restored.amount, 129.0)
            event.refresh_from_db()
            self.assertNotIn("carbon_calculation", event.extra_data or {})
            self.assertTrue(DataOperationLog.objects.filter(action="restore").exists())
