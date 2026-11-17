"""Weather activities."""

from django.core.exceptions import ValidationError
from django.db import models

from .common_event import CommonEvent


class WeatherEvent(CommonEvent):
    FROST = "FR"
    DROUGHT = "DR"
    HAILSTORM = "HL"
    HIGH_TEMPERATURE = "HT"
    TROPICAL_STORM = "TS"
    HIGH_WINDS = "HW"
    HIGH_HUMIDITY = "HH"
    LOW_HUMIDITY = "LH"

    WEATHER_EVENTS = (
        (FROST, "Frost"),
        (DROUGHT, "Drought"),
        (HAILSTORM, "Hailstorm"),
        (HIGH_TEMPERATURE, "High Temperature"),
        (TROPICAL_STORM, "Tropical Storm"),
        (HIGH_WINDS, "High Winds"),
        (HIGH_HUMIDITY, "High Humidity"),
        (LOW_HUMIDITY, "Low Humidity"),
    )

    type = models.CharField(
        max_length=2,
        choices=WEATHER_EVENTS,
    )
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Plausibility ranges for meteorological magnitudes. These are NOT
    # regulatory thresholds — they're sanity bounds to catch unit-of-measure
    # mistakes (e.g. °C entered in a °F field, kph in an mph field) before the
    # value ships in an inspector-facing PDF. An entry like 140°F on a
    # California farm is instantly implausible (world-record high is ~134°F,
    # Death Valley 1913) and undermines credibility of the rest of the data.
    _PLAUSIBILITY_BOUNDS = {
        # temperature in °F / °C (evaluated against both, narrower of the two)
        "temperature_f": (-40, 135),  # world record high ~134°F
        "temperature_c": (-40, 57),  # world record high ~56.7°C
        # F12 fix (2026-06): the WeatherTab form collects wind in km/h and
        # precipitation in mm (metric), so the stored extra_data values are metric.
        # Bounds were imperial (mph / inches), so a legitimate 150 mm storm or a
        # 300 km/h gust failed the (0,50)/(0,250) checks with a 400. Bounds are now
        # metric to match the form's units.
        "wind_speed_kmh": (0, 410),  # world record gust 253 mph ≈ 407 km/h (Barrow Island)
        "precipitation_mm": (0, 1200),  # single-event max ~43 in ≈ 1092 mm (TC Denise, 1966)
        "humidity_pct": (0, 100),
        "hail_size_in": (0, 8),  # largest verified ~8 in (Vivian, SD 2010)
    }

    def _plausibility_check(self, unit: str, value, low: float, high: float, field: str):
        """Return a ValidationError-style message if the magnitude is outside
        plausible meteorological bounds, else None. Used by clean() and by
        the serializer's pre-save validation so both the admin and the API
        catch unit-of-measure typos."""
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None  # non-numeric handled elsewhere
        if numeric < low or numeric > high:
            return (
                f"{field} {numeric}{unit} is outside the plausible range "
                f"[{low}, {high}]{unit}. Check that the value was entered in "
                "the correct unit — e.g. °C in a °F field will trigger this."
            )
        return None

    def clean(self):
        """
        Validate that numeric meteorological magnitudes are within plausible
        ranges. Catches °C-in-°F and kph-in-mph typos at save-time so they
        never ship in an inspector-facing PDF.
        """
        from django.core.exceptions import ValidationError

        super().clean()
        extra = self.extra_data or {}
        issues = {}

        # Temperature — unit-aware; extra_data.temperature_unit in {"F", "C"}.
        temp_unit = (extra.get("temperature_unit") or "F").upper()
        temp_bounds_key = "temperature_c" if temp_unit == "C" else "temperature_f"
        low, high = self._PLAUSIBILITY_BOUNDS[temp_bounds_key]
        unit_sym = "°C" if temp_unit == "C" else "°F"
        for key in ("highest_temperature", "lowest_temperature", "temperature", "lower_temperature"):
            msg = self._plausibility_check(unit_sym, extra.get(key), low, high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        wind_low, wind_high = self._PLAUSIBILITY_BOUNDS["wind_speed_kmh"]
        msg = self._plausibility_check(" km/h", extra.get("wind_speed"), wind_low, wind_high, "wind_speed")
        if msg:
            issues.setdefault("extra_data", []).append(msg)

        precip_low, precip_high = self._PLAUSIBILITY_BOUNDS["precipitation_mm"]
        for key in ("precipitation", "precipitation_amount"):
            msg = self._plausibility_check(" mm", extra.get(key), precip_low, precip_high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        hum_low, hum_high = self._PLAUSIBILITY_BOUNDS["humidity_pct"]
        # Check both humidity key variants separately — using ``or`` to pick
        # between them treats 0% (a valid low-humidity reading) as falsy
        # and silently swaps it for humidity_level, masking a real value.
        for key in ("humidity", "humidity_level"):
            msg = self._plausibility_check("%", extra.get(key), hum_low, hum_high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        hail_low, hail_high = self._PLAUSIBILITY_BOUNDS["hail_size_in"]
        msg = self._plausibility_check(" in", extra.get("hail_size"), hail_low, hail_high, "hail_size")
        if msg:
            issues.setdefault("extra_data", []).append(msg)

        if issues:
            raise ValidationError(issues)
