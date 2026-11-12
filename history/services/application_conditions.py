"""
State application facts on a spray record: what the conditions, the apparatus and the people
were, and how every printed surface words them (overall review 2026-11, OV-FJ-C11).

WAC 16-228-1320(1) (WSR 25-22-065, effective 2026-01-01) covers "all persons applying pesticides
to more than one acre of agricultural land in a calendar year", with no restricted-use
distinction, so an organic orchard spraying spinosad is covered. Items Trazo held in the wrong
shape or not at all, and the columns that now hold them on `ChemicalEvent`:

* (e) wind direction and estimated speed in mph, temperature in degrees Fahrenheit:
  `wind_from`, `wind_speed_mph`, `air_temperature_f`. Not required for bait stations,
  within-structure applications, or drip or subsurface irrigation.
* (h) concentration "may be recorded as" gallons per acre of output volume: `carrier_volume` +
  `carrier_volume_unit`.
* (k) apparatus license plate number: `apparatus_license_plate`.
* (l) the licensed applicator's complete address and telephone number: `applicator_address`,
  `applicator_phone`, copied onto the record so a later profile edit never rewrites it.
* (n) for a commercial application, the firm's complete address: `commercial_firm_address`.

This module stores nothing and decides nothing about any state's law: it prints what the operator
typed. A later export names the blank items; no copy here says a record "satisfies" a rule.

The certifier packet, the audit CSV and the model/serializer rule all read from here, so the two
documents a certifier holds cannot word the same reading two ways. It imports no model.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

#: Application methods for which WAC 16-228-1320(1)(e) does not ask for wind or temperature.
#: Only the codes Trazo has: `drip` (backend APPLICATION_METHOD) and `subsurface` (the
#: fertilizer form). The rule also exempts bait stations and within-structure applications;
#: Trazo has no method code for either, so none is listed until one exists.
CONDITIONS_EXEMPT_METHODS = frozenset({"drip", "subsurface"})

#: How each carrier unit prints.
CARRIER_UNIT_TEXT = {
    "gal_per_acre": "gal/acre",
    "gal_total": "gal total",
    "l_per_ha": "L/ha",
}

CARRIER_UNIT_MISSING = "Pick the unit for the carrier volume."
CARRIER_VOLUME_MISSING = "Enter the carrier volume, or clear its unit."


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def carrier_conflicts(carrier_volume, carrier_volume_unit) -> dict:
    """A carrier volume and its unit stand or fall together.

    A number with no unit measures nothing, and a unit with no number is a denominator attached
    to silence (the same rule the label rate follows). Returns {field: message}; empty when fine.
    """
    if not _blank(carrier_volume) and _blank(carrier_volume_unit):
        return {"carrier_volume_unit": CARRIER_UNIT_MISSING}
    if _blank(carrier_volume) and not _blank(carrier_volume_unit):
        return {"carrier_volume": CARRIER_VOLUME_MISSING}
    return {}


def _number(value) -> Optional[str]:
    """A reading as the operator would write it: 4, 4.5, 62, -3.5. Never "4.0" or "62.00"."""
    if _blank(value):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value).strip()
    text = format(number.normalize(), "f")
    return "0" if text in ("-0", "") else text


def application_method_code(event) -> str:
    """The method code the packet already prints: the structured column, else the legacy one."""
    method = getattr(event, "application_method_structured", None) or getattr(event, "way_of_application", None)
    return str(method or "").strip()


def conditions_not_applicable(event) -> bool:
    """True when the method is one for which wind and temperature are not asked."""
    return application_method_code(event).lower() in CONDITIONS_EXEMPT_METHODS


def not_applicable_text(event, method_label) -> str:
    """ "Not applicable (Drip / fertigation)": the method, in the packet's own label for it."""
    code = application_method_code(event)
    label = method_label(code) if method_label else code
    return f"Not applicable ({label or code})"


def wind_text(event, method_label=None) -> Optional[str]:
    """ "from NW at 4 mph", "calm", or the not-applicable line; None when nothing was recorded.

    A half reading says which half is missing rather than printing a lone number: "4 mph" with
    no direction does not say where the drift went.
    """
    direction = (getattr(event, "wind_from", "") or "").strip()
    speed = _number(getattr(event, "wind_speed_mph", None))
    if direction == "calm":
        return f"calm, {speed} mph" if speed is not None else "calm"
    if direction and speed is not None:
        return f"from {direction} at {speed} mph"
    if direction:
        return f"from {direction}, speed not recorded"
    if speed is not None:
        return f"{speed} mph, direction not recorded"
    if conditions_not_applicable(event):
        return not_applicable_text(event, method_label)
    return None


def air_temperature_text(event, method_label=None) -> Optional[str]:
    """ "62 °F", or the not-applicable line; None when nothing was recorded."""
    reading = _number(getattr(event, "air_temperature_f", None))
    if reading is not None:
        return f"{reading} °F"
    if conditions_not_applicable(event):
        return not_applicable_text(event, method_label)
    return None


def carrier_text(event) -> Optional[str]:
    """ "100 gal/acre"; a volume whose unit is missing says so."""
    volume = _number(getattr(event, "carrier_volume", None))
    if volume is None:
        return None
    unit = CARRIER_UNIT_TEXT.get((getattr(event, "carrier_volume_unit", "") or "").strip())
    return f"{volume} {unit}" if unit else f"{volume} (unit not recorded)"


def _text(event, name) -> Optional[str]:
    value = (getattr(event, name, "") or "").strip()
    return value or None


def application_conditions(event, method_label=None) -> list:
    """Every state application fact on this record that has something to print, in order.

    `[(label, text), ...]`. Wind and temperature appear as "Not applicable (method)" for an
    exempt method rather than as a blank; everything else appears only when recorded.
    """
    rows = [
        ("Wind", wind_text(event, method_label)),
        ("Air temperature", air_temperature_text(event, method_label)),
        ("Carrier", carrier_text(event)),
        ("Apparatus plate", _text(event, "apparatus_license_plate")),
        ("Applicator address", _text(event, "applicator_address")),
        ("Applicator phone", _text(event, "applicator_phone")),
        ("Firm address", _text(event, "commercial_firm_address")),
    ]
    return [(label, text) for label, text in rows if text]
