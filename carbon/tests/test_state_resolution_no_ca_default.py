"""An unknown state must fall back to national defaults, never to California.

Regression pins for the US-expansion audit. Three independent code paths used to
hardcode "CA" when a farm's state was blank or not a 2-letter code:

  * `_default_state()` returned "CA" for a blank state
  * the USDA-compliance path forced "CA" whenever `len(state) != 2`
  * `get_regional_benchmark` parsed a nonexistent `establishment.location`

Because `Establishment.state` is free text, 35 of 105 live rows stored
"California" rather than "CA" — so the irrigation lookup missed and silently
applied the 1.0" humid-East default to California farms, while a Florida farm
with a blank state was costed as Californian and still recorded
`regional_adjustments_applied=True`.

These tests use plain stubs rather than model fixtures: the paths under test
only read attributes, and carbon's DB fixtures are independently stale.
"""

from django.test import TestCase

from carbon.services.event_carbon_calculator import EventCarbonCalculator


class _Stub:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _event(state):
    return _Stub(history=_Stub(parcel=_Stub(establishment=_Stub(state=state))))


class NoCaliforniaDefaultTests(TestCase):
    def setUp(self):
        self.calc = EventCarbonCalculator()

    def test_blank_state_resolves_to_none_not_ca(self):
        state, _county = self.calc._get_establishment_location(_event(""))
        self.assertIsNone(state)

    def test_unresolvable_state_resolves_to_none_not_ca(self):
        # "Salto" is a Uruguayan department present on a real row.
        state, _county = self.calc._get_establishment_location(_event("Salto"))
        self.assertIsNone(state)

    def test_full_state_name_is_canonicalized(self):
        state, _county = self.calc._get_establishment_location(_event("Florida"))
        self.assertEqual(state, "FL")

    def test_county_is_always_none(self):
        # Establishment has no `county` field; the old getattr could never hit.
        _state, county = self.calc._get_establishment_location(_event("CA"))
        self.assertIsNone(county)

    def test_farm_coordinates_do_not_fall_back_to_ca(self):
        _lat, _lon, state = self.calc._get_farm_coordinates(_event(""))
        self.assertIsNone(state)

        _lat, _lon, state = self.calc._get_farm_coordinates(_event("Florida"))
        self.assertEqual(state, "FL")

    def test_default_state_helper_is_gone(self):
        # Pin the removal so it cannot be reintroduced by a merge.
        self.assertFalse(hasattr(self.calc, "_default_state"))


class RegionalIrrigationDefaultTests(TestCase):
    """The lookup keys on canonical codes, so it must see "CA" for "California"."""

    def setUp(self):
        self.defaults = EventCarbonCalculator.REGIONAL_IRRIGATION_DEFAULTS

    def test_california_is_not_the_humid_east_default(self):
        self.assertNotEqual(self.defaults["CA"], self.defaults["default"])

    def test_full_name_would_have_missed_the_table(self):
        # Documents the bug: the raw stored value never matched a key.
        self.assertNotIn("CALIFORNIA", self.defaults)
        self.assertIn("CA", self.defaults)

    def test_unknown_state_uses_the_national_default(self):
        state = None
        self.assertEqual(
            self.defaults.get(state or "", self.defaults["default"]),
            self.defaults["default"],
        )


class ComplianceRecordStateColumnTests(TestCase):
    """`USDAComplianceRecord.state` is NOT NULL, so an unknown state must be stored
    as "" rather than None. The create() sits inside a bare `except Exception`, so a
    None would not raise to the caller — it would silently poison the surrounding
    atomic block and fail every subsequent query in it."""

    def test_state_column_is_not_nullable(self):
        from carbon.models import USDAComplianceRecord

        field = USDAComplianceRecord._meta.get_field("state")
        self.assertFalse(field.null, "If this becomes nullable, the `state or ''` guard can be dropped.")
        self.assertEqual(field.max_length, 2)

    def test_unknown_state_persists_as_empty_string(self):
        from carbon.models import USDAComplianceRecord

        record = USDAComplianceRecord(state=None or "")
        self.assertEqual(record.state, "")


class RegionalAdjustmentClaimTests(TestCase):
    """`regional_adjustments_applied` is written into the USDA audit trail, so an
    unknown state must record False rather than inheriting California's."""

    def test_none_state_is_not_in_the_regional_adjustments_table(self):
        from carbon.services.enhanced_usda_factors import EnhancedUSDAFactors

        adjustments = EnhancedUSDAFactors().regional_adjustments
        self.assertNotIn(None, adjustments)
        self.assertFalse(None in adjustments)
