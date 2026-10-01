"""
Phase 1 / B1 + B2 + B4 — the weather section of the certifier PDF.

Three defects, all of which produced a document that looked complete and was not:

B1  The exporter probed ``lowest_temperature`` / ``precipitation`` / ``humidity``, but
    UpdateWeatherEventSerializer writes ``lower_temperature`` / ``precipitation_amount`` /
    ``humidity_level``. Frost temperature, storm rainfall and humidity therefore never
    rendered — the Magnitude cell was simply blank, with nothing to indicate data was lost.

B2  Wind was labelled " mph" and precipitation " in", but WeatherTab collects km/h and mm
    (its own labels say so, and WeatherEvent._PLAUSIBILITY_BOUNDS is metric to match). The
    exporter was stating the wrong unit on an inspector-facing document — a 150 mm storm
    read as "150 in".

B4  way_of_protection / protection_measures / duration / water_deficit / damage_assessment /
    crop_impact were collected and never rendered anywhere. § 205.201(a)(3) is a monitoring
    *plan*: what the operation did about the weather is the point.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, WeatherEvent
from history.services.audit_export_service import AuditExportService, _weather_magnitudes
from product.models import Parcel, Product
from users.models import User


class WeatherMagnitudeHelperTests(TestCase):
    """Unit-level cover for the key-name and unit table, independent of PDF layout."""

    def test_reads_the_keys_the_serializer_actually_writes(self):
        self.assertEqual(
            _weather_magnitudes({"lower_temperature": 28, "temperature_unit": "F"}),
            ["min 28°F"],
        )
        self.assertEqual(_weather_magnitudes({"precipitation_amount": 150}), ["150 mm"])
        self.assertEqual(_weather_magnitudes({"humidity_level": 85}), ["85%"])

    def test_still_reads_legacy_key_spellings(self):
        self.assertEqual(_weather_magnitudes({"precipitation": 90}), ["90 mm"])
        self.assertEqual(_weather_magnitudes({"humidity": 20}), ["20%"])
        # Unit unstated, so it takes the serializer's stored default of C — this line
        # previously asserted °F and was encoding the very mismatch that put a -2°C frost
        # on the certifier packet as "-2°F". See TemperatureUnitContractTests below.
        self.assertEqual(_weather_magnitudes({"lowest_temperature": 30}), ["min 30°C"])

    def test_min_and_max_temperature_are_distinct_measurements(self):
        # Grouping them as one "temperature" concept would print only the max and silently
        # drop the min. They are different readings and must both survive, each labelled so
        # an inspector is not left guessing which number is which.
        out = _weather_magnitudes({"highest_temperature": 95, "lower_temperature": 28, "temperature_unit": "F"})
        self.assertEqual(out, ["max 95°F", "min 28°F"])

    def test_wind_and_precipitation_use_metric_units(self):
        out = _weather_magnitudes({"wind_speed": 120, "precipitation_amount": 150})
        self.assertEqual(out, ["120 km/h", "150 mm"])
        self.assertNotIn("120 mph", out)
        self.assertNotIn("150 in", out)

    def test_reports_every_magnitude_not_just_the_first(self):
        # A tropical storm records wind AND rainfall AND duration. The old
        # break-on-first-match printed only one of them.
        out = _weather_magnitudes({"wind_speed": 100, "precipitation_amount": 200})
        self.assertEqual(len(out), 2)

    def test_one_reading_per_concept_even_when_both_spellings_present(self):
        out = _weather_magnitudes({"precipitation_amount": 150, "precipitation": 90})
        self.assertEqual(out, ["150 mm"])

    def test_celsius_is_labelled_celsius(self):
        self.assertEqual(
            _weather_magnitudes({"lower_temperature": -2, "temperature_unit": "C"}),
            ["min -2°C"],
        )

    def test_zero_is_a_reading_not_a_missing_value(self):
        # 0% humidity / 0 mm are legitimate readings; a truthiness check would drop them.
        self.assertEqual(_weather_magnitudes({"humidity_level": 0}), ["0%"])

    def test_empty_and_non_dict_input_are_safe(self):
        self.assertEqual(_weather_magnitudes({}), [])
        self.assertEqual(_weather_magnitudes(None), [])


class WeatherSectionRenderTests(TestCase):
    """End-to-end: the values must appear in the rendered PDF flowables."""

    def setUp(self):
        self.user = User.objects.create_user(email="weather@test.com", password="x")
        self.company = Company.objects.create(name="Weather Farm")
        self.establishment = Establishment.objects.create(name="WE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="W-parcel", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="Weather Production",
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

    def _weather_text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        out = []
        for el in svc._build_weather_section():
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    text = getattr(cell, "text", None)
                    if text:
                        out.append(text)
            # Sub-section headers are bare Paragraphs, not table cells.
            paragraph_text = getattr(el, "text", None)
            if paragraph_text:
                out.append(paragraph_text)
        return " ".join(out)

    def test_frost_temperature_renders(self):
        WeatherEvent.objects.create(
            history=self.history,
            type="FR",
            date=timezone.now(),
            description="Frost night",
            extra_data={
                "lower_temperature": 28,
                "temperature_unit": "F",
                "way_of_protection": "wind machines",
            },
        )
        text = self._weather_text()
        self.assertIn("28°F", text)
        self.assertIn("Frost", text)

    def test_storm_precipitation_renders_in_millimetres(self):
        WeatherEvent.objects.create(
            history=self.history,
            type="TS",
            date=timezone.now(),
            description="Storm",
            extra_data={
                "wind_speed": 120,
                "precipitation_amount": 150,
                "damage_assessment": "Minor limb loss in block 3",
            },
        )
        text = self._weather_text()
        self.assertIn("150 mm", text)
        self.assertIn("120 km/h", text)
        self.assertNotIn("150 in", text)
        self.assertNotIn("120 mph", text)

    def test_humidity_renders(self):
        WeatherEvent.objects.create(
            history=self.history,
            type="HH",
            date=timezone.now(),
            description="Humid spell",
            extra_data={"humidity_level": 85, "crop_impact": "Increased mildew watch"},
        )
        self.assertIn("85%", self._weather_text())

    def test_response_subtable_renders_protective_action(self):
        WeatherEvent.objects.create(
            history=self.history,
            type="FR",
            date=timezone.now(),
            description="Frost night",
            extra_data={
                "lower_temperature": 30,
                "temperature_unit": "F",
                "way_of_protection": "wind machines",
                "duration": 240,
            },
        )
        text = self._weather_text()
        self.assertIn("Weather Response", text)
        self.assertIn("wind machines", text)
        self.assertIn("240", text)

    def test_duration_unit_follows_the_subtype(self):
        """WeatherTab labels duration "minutes" for hail and "hours" for storms/wind/humidity.

        The stored value carries no unit, so printing the wrong one is a 60-fold
        misstatement on an inspector-facing document.
        """
        WeatherEvent.objects.create(
            history=self.history,
            type="HL",
            date=timezone.now(),
            description="Hail",
            extra_data={"duration": 12, "way_of_protection": "hail nets"},
        )
        WeatherEvent.objects.create(
            history=self.history,
            type="HW",
            date=timezone.now(),
            description="Wind",
            extra_data={"duration": 6, "protection_measures": "checked ties"},
        )
        text = self._weather_text()
        self.assertIn("Duration (min): 12", text)
        self.assertIn("Duration (hrs): 6", text)

    def test_response_subtable_absent_when_nothing_was_recorded(self):
        # A plain observation must not produce an empty "Weather Response" table.
        WeatherEvent.objects.create(
            history=self.history,
            type="DR",
            date=timezone.now(),
            description="Dry stretch",
            extra_data={},
        )
        self.assertNotIn("Weather Response", self._weather_text())

    def test_section_renders_with_no_weather_events(self):
        self.assertIn("Weather", self._weather_text())


class TemperatureUnitContractTests(TestCase):
    """The PDF's fallback unit must match what the serializer actually stores.

    history/serializers.py writes extra_data["temperature_unit"] = "C" when the field is absent.
    The exporter defaulted to "F", so every event without an explicit unit — all seeded rows, and
    anything posted by a client that omits it — rendered a -2°C frost as "-2°F" on the certifier
    packet. Found by reading a real generated PDF whose own field note said "Min temp -2C".
    """

    def test_absent_unit_matches_the_serializer_default(self):
        from history.services.audit_export_service import _weather_magnitudes

        magnitudes = _weather_magnitudes({"lower_temperature": "-2"})
        self.assertEqual(magnitudes, ["min -2°C"])

    def test_an_explicit_unit_is_honoured(self):
        from history.services.audit_export_service import _weather_magnitudes

        self.assertEqual(
            _weather_magnitudes({"lower_temperature": "28", "temperature_unit": "F"}),
            ["min 28°F"],
        )

    def test_an_unreadable_unit_asserts_neither(self):
        from history.services.audit_export_service import _weather_magnitudes

        self.assertEqual(_weather_magnitudes({"temperature": "10", "temperature_unit": "??"}), ["10°"])
