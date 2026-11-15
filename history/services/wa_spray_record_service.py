"""
Washington pesticide application records (WAC 16-228-1320), printed from the spray records Trazo
holds (overall review 2026-11, OV-RK-C03, the output half).

WHY
---
WAC 16-228-1320 (WSR 25-22-065, effective 2026-01-01) asks "Certified applicators and all persons
applying pesticides to more than one acre of agricultural land in a calendar year" to keep a record
of every application. There is no restricted-use distinction, so an organic orchard spraying
spinosad is covered. Subsection (1) lists fourteen items, (a) to (n); subsection (5) lets the
department "accept pesticide application records on any physical or electronic form" that
"contains all the information required by subsection (1)" and is "in a form and format acceptable
to the department". Slices 1 to 4 store every item; this module prints them.

WHAT A PAGE SHOWS
-----------------
One block per application pass, for one farm and one period. A tank (the records sharing
`tank_mix_group` on one season and block, `history/services/tank_mix.py`) prints ONCE, with every
product line under it: (d), (f), (g), (h) and (i) are per product, the rest belong to the pass.
Every row is labelled with its item letter. An item the record does not hold prints one of three
phrases, never a value taken from somewhere else:

* NOT_RECORDED, "Not recorded": nothing was entered.
* NOT_ON_SOURCE_RECORD, "Not on the source record": the operator marked it so
  (`history/services/not_on_source_record.py`).
* "Not applicable (<method>)": wind and temperature for a method (1)(e) exempts
  (`history/services/application_conditions.py`).

Each block ends with the letters of its blank items. The applicator's address is never the farm's;
a start time is never the noon placeholder of a day-only record; an amount per acre worked out from
two recorded numbers says so.

WHAT IT NEVER SAYS
------------------
That the document "satisfies" the rule, is "compliant", or is approved by anyone. Whether the
department accepts the form is the department's decision (subsection (5)), and the copy says that
and stops. Guarded in `history/tests/test_wa_spray_record_export.py`.

SCOPE
-----
Pesticide, fungicide and herbicide records (the same types the CA PUR reads). A fertilizer is not a
pesticide and is left out. Unlike the CA PUR, an application made by a commercial firm stays in:
the rule asks the farm's record to name the firm, item (n).

TIMES
-----
`application_start` / `application_end` are the wall clock the operator typed, stored as UTC
(`history/models.py`, ChemicalEvent.application_start), so they print verbatim. The day a record
was entered is an instant from the audit log (events carry no `created_at`; the retention floor
reads the same log), printed in Pacific time: Washington lies wholly in that zone, and Trazo stores
no per-farm zone, so for a Washington farm this is a fact rather than a guess.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from common.field_registry import UNIT_APPLICATION_RATE, volume_unit_symbol
from common.specimen import SPECIMEN_BODY, SPECIMEN_LINE, SPECIMEN_TITLE, is_specimen, specimen_page_callback
from history.constants import CHEMICAL_EVENT_TYPE
from history.services.application_conditions import (
    air_temperature_text,
    carrier_text,
    conditions_not_applicable,
    wind_text,
)
from history.services.not_on_source_record import NOT_ON_SOURCE_RECORD
from history.services.pur_export_service import REPORTABLE_TYPES, _acres, _area_for_pur

RULE = "WAC 16-228-1320"

#: The record types this export prints: pesticides, fungicides, herbicides. A fertilizer is not a
#: pesticide application. The retention floor for Washington reads the same tuple.
WA_RECORD_TYPES = REPORTABLE_TYPES

#: Washington lies wholly in Pacific time (see module notes).
WA_TIME_ZONE = ZoneInfo("America/Los_Angeles")

NOT_RECORDED = "Not recorded"

#: Row statuses. Only BLANK and NOT_ON_SOURCE name an item as blank; NOT_APPLICABLE does not.
VALUE = "value"
BLANK = "not_recorded"
NOT_ON_SOURCE = "not_on_source_record"
NOT_APPLICABLE = "not_applicable"
#: A row that may be blank without blanking its item, because another row can carry the item
#: (the carrier volume is one of the forms (h) allows; a product's own concentration is another).
ALTERNATIVE = "alternative"
_BLANK_STATUSES = (BLANK, NOT_ON_SOURCE)

#: WAC 16-228-1320(1), as each block labels its items.
ITEMS = (
    ("a", "Person for whom the pesticide was applied"),
    ("b", "Location of the land"),
    ("c", "Date, start and stop time"),
    ("d", "Product name and EPA registration number"),
    ("e", "Wind direction, wind speed, temperature"),
    ("f", "Total amount applied"),
    ("g", "Amount applied per acre"),
    ("h", "Concentration"),
    ("i", "Pests targeted (PCO classification)"),
    ("j", "Crop or site treated"),
    ("k", "Apparatus license plate number"),
    ("l", "Licensed applicator and who made the application"),
    ("m", "Number of acres treated"),
    ("n", "Commercial firm"),
)
ITEM_LETTERS = tuple(letter for letter, _label in ITEMS)

HEADER_STATEMENT = (
    "Each item of WAC 16-228-1320(1) is listed; an item not on the record is named. Whether the "
    "Washington State Department of Agriculture accepts this form is the department's decision "
    "(WAC 16-228-1320(5))."
)

_RATE_LABEL = dict(UNIT_APPLICATION_RATE)

#: How the record names an application method on this document.
_METHOD_LABEL = {
    "broadcast": "Broadcast",
    "injection": "Soil injection",
    "foliar": "Foliar",
    "drip": "Drip / fertigation",
    "fertigation": "Fertigation",
    "subsurface": "Subsurface",
    "banding": "Banded",
    "ground_spray": "Ground spray",
    "air_blast": "Air-blast",
    "aerial": "Aerial",
    "fumigation": "Fumigation",
    "chemigation": "Chemigation",
    "soil_incorporation": "Soil incorporation",
    "hand_dispenser": "Hand-placed dispensers",
}


def _method_label(code):
    key = str(code or "").strip()
    if not key:
        return ""
    return _METHOD_LABEL.get(key, key.replace("_", " ").capitalize())


def _s(value) -> str:
    return "" if value is None else str(value).strip()


def _num(value) -> str:
    """A number as the operator would write it: 4, 4.5, 12, never "12.00"."""
    text = _s(value)
    if not text:
        return ""
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    out = format(number.normalize(), "f")
    return "0" if out in ("-0", "") else out


def _or_blank(text):
    text = _s(text)
    return (text, VALUE) if text else (NOT_RECORDED, BLANK)


@dataclass
class Row:
    """One printed row: the item letter, what the row is, and what the record holds."""

    item: str
    label: str
    text: str
    status: str = VALUE

    @property
    def is_blank(self) -> bool:
        return self.status in _BLANK_STATUSES


@dataclass
class ProductLine:
    """One product of a pass: items (d), (f), (g), (h), (i)."""

    number: str
    role: str
    event_id: int | None
    name: Row
    epa: Row
    total: Row
    per_acre: Row
    concentration: Row
    pests: Row

    @property
    def rows(self):
        return [self.name, self.epa, self.total, self.per_acre, self.concentration, self.pests]


@dataclass
class ApplicationPass:
    number: int
    events: list
    parcel: object
    #: The pass's day when every line holds the same one, else None (see `applied_text`).
    applied_on: date | None
    #: The day as item (c) prints it: one day, or "line 1: ...; line 2: ..." when lines differ.
    applied_text: str = ""
    #: Whether this pass's parcel has a map page (`_map_drawing` succeeded).
    mapped: bool = False
    before: list = field(default_factory=list)  # (a), (b), (c)
    products: list = field(default_factory=list)
    after: list = field(default_factory=list)  # (e), (h) carrier, (j) to (n)
    entered: str = ""
    notes: list = field(default_factory=list)

    @property
    def is_tank(self) -> bool:
        return len(self.products) > 1

    def blank_items(self) -> list:
        """The letters of the items this record leaves blank, in rule order."""
        blank = set()
        rows = self.before + self.after + [row for line in self.products for row in line.rows]
        for row in rows:
            if row.is_blank and row.item != "h":
                blank.add(row.item)
        # (h): a product's concentration, or the carrier volume of the pass. Blank only when a
        # product holds neither.
        carrier_held = any(row.item == "h" and row.status == VALUE for row in self.after)
        if not carrier_held and any(line.concentration.is_blank for line in self.products):
            blank.add("h")
        return [letter for letter in ITEM_LETTERS if letter in blank]

    def blank_line(self) -> str:
        blank = self.blank_items()
        if not blank:
            return "No item of (1)(a) to (1)(n) is blank on this record."
        return "Items not on this record: " + ", ".join(f"({letter})" for letter in blank) + "."


def _line_number(event) -> str:
    return str(event.tank_mix_line) if getattr(event, "tank_mix_line", None) else "1"


def _shared(events, item, label, getter) -> Row:
    """A pass-level row read from every line of the pass.

    The lines of one tank are written with the same shared values, but a correction can change one
    line alone. When they disagree the row prints each line's value rather than picking one.
    """
    values = [getter(event) for event in events]
    if all(value == values[0] for value in values):
        text, status = values[0]
        return Row(item, label, text, status)
    text = "; ".join(f"line {_line_number(event)}: {value[0]}" for event, value in zip(events, values))
    statuses = {value[1] for value in values}
    status = next((s for s in (BLANK, NOT_ON_SOURCE) if s in statuses), VALUE)
    return Row(item, label, text, status)


#: The size the map page draws at. The predicate that decides whether a parcel HAS a map uses the
#: same call, so the (b) row, the preview's `parcels_without_map` and the map pages always agree.
_MAP_SIZE_IN = (7.0, 4.6)


def _map_drawing(parcel):
    """The parcel's map page drawing, or None when the recorded boundary cannot be drawn.

    `parcel_boundary_ring` alone is not the test: a ring can exist and still be degenerate (four
    copies of one point), which `parcel_map_drawing` refuses."""
    if parcel is None:
        return None
    from reportlab.lib.units import inch

    from certifications.services.parcel_map import parcel_map_drawing

    width, height = _MAP_SIZE_IN
    return parcel_map_drawing(parcel, width=width * inch, height=height * inch)


#: Item (b)'s map row, per format. The CSV has no pages, so it points at the PDF export.
NO_MAP_TEXT = "Not included: no parcel boundary that can be drawn is recorded in Trazo."


def map_text(parcel_name, mapped, file_format="pdf") -> str:
    if not mapped:
        return NO_MAP_TEXT
    where = (
        "in the PDF export of these records" if file_format == "csv" else "on the map pages at the end of this document"
    )
    return (
        f"Schematic of {parcel_name or 'the parcel'} {where}, drawn from the boundary recorded in Trazo. "
        "It is not the map on the department's adopted form."
    )


def _day(when) -> date | None:
    """The calendar day of a stored event date, read in UTC like every other surface."""
    if when is None:
        return None
    from datetime import timezone as dt_timezone

    if getattr(when, "tzinfo", None) is not None:
        when = when.astimezone(dt_timezone.utc)
    return when.date() if hasattr(when, "date") else when


def _clock(when, day) -> str:
    """A wall-clock start or stop time as typed (stored as UTC, printed verbatim)."""
    if when is None:
        return ""
    stamped = _day(when)
    clock = when.strftime("%H:%M") if hasattr(when, "strftime") else str(when)
    return clock if stamped == day else f"{stamped.isoformat()} {clock}"


class WASprayRecordService:
    """Washington pesticide application records for one establishment and period."""

    def __init__(self, establishment, start: date, end: date):
        self.establishment = establishment
        self.start = start
        self.end = end
        self._built = None

    @classmethod
    def for_year(cls, establishment, year: int):
        return cls(establishment, date(int(year), 1, 1), date(int(year), 12, 31))

    # ------------------------------------------------------------------
    @property
    def period_label(self) -> str:
        if self.start == date(self.start.year, 1, 1) and self.end == date(self.start.year, 12, 31):
            return str(self.start.year)
        return f"{self.start.isoformat()} to {self.end.isoformat()}"

    @property
    def period_slug(self) -> str:
        if self.period_label == str(self.start.year):
            return str(self.start.year)
        return f"{self.start.isoformat()}_{self.end.isoformat()}"

    def header_text(self) -> str:
        return f"Pesticide application records for {self.establishment.name}, {self.period_label}. {HEADER_STATEMENT}"

    # ------------------------------------------------------------------
    def _records(self):
        from history.models import ChemicalEvent

        return list(
            ChemicalEvent.objects.filter(
                history__parcel__establishment=self.establishment,
                type__in=WA_RECORD_TYPES,
                date__date__gte=self.start,
                date__date__lte=self.end,
            )
            .select_related("history__parcel", "history__product", "history__crop_type")
            .prefetch_related("history__parcel__planned_crops")
            .order_by("date", "pk")
        )

    @staticmethod
    def _entered_on(events) -> dict:
        """{event pk: the day its record was created, in Pacific time} from the audit log."""
        if not events:
            return {}
        from django.contrib.contenttypes.models import ContentType

        from auditlog.models import LogEntry

        content_type = ContentType.objects.get_for_model(type(events[0]))
        stamps = {}
        for object_pk, timestamp in LogEntry.objects.filter(
            content_type=content_type,
            object_pk__in=[str(event.pk) for event in events],
            action=LogEntry.Action.CREATE,
        ).values_list("object_pk", "timestamp"):
            current = stamps.get(object_pk)
            if current is None or timestamp < current:
                stamps[object_pk] = timestamp
        return {int(pk): stamp.astimezone(WA_TIME_ZONE).date() for pk, stamp in stamps.items()}

    @staticmethod
    def _group(records):
        """Records grouped into passes: a tank on one season and block is one pass."""
        passes, index = [], {}
        for record in records:
            if record.tank_mix_group:
                key = ("tank", record.tank_mix_group, record.history_id, record.block_id or "")
            else:
                key = ("record", record.pk)
            if key not in index:
                index[key] = len(passes)
                passes.append([])
            passes[index[key]].append(record)
        for lines in passes:
            lines.sort(key=lambda e: (e.tank_mix_line if e.tank_mix_line is not None else 10**6, e.pk))
        return passes

    # ------------------------------------------------------------------
    def _operator_rows(self) -> list:
        """(a): the operation's name and address, from the company profile, else the farm's."""
        est = self.establishment
        company = getattr(est, "company", None)
        name = _s(getattr(company, "name", None))
        trade = _s(getattr(company, "tradename", None))
        name_text = f"{name} (doing business as {trade})" if name and trade and trade != name else name
        rows = [Row("a", "Name", *_or_blank(name_text))]

        def _parts(obj):
            return [
                ("street address", _s(getattr(obj, "address", None))),
                ("city", _s(getattr(obj, "city", None))),
                ("state", _s(getattr(obj, "state", None))),
                ("ZIP code", _s(getattr(obj, "zip_code", None))),
            ]

        parts, source = _parts(company), "company profile"
        if not any(value for _label, value in parts):
            parts, source = _parts(est), "farm profile"
        held = [value for _label, value in parts if value]
        missing = [label for label, value in parts if not value]
        if not held:
            rows.append(Row("a", "Address", NOT_RECORDED, BLANK))
            return rows
        text = f"{', '.join(held)} (from the {source})"
        if missing:
            text += f"; {', '.join(missing)} not recorded"
        rows.append(Row("a", "Address", text, BLANK if missing else VALUE))
        return rows

    def _location_rows(self, events, parcel, mapped) -> list:
        """(b): parcel and block, a location the record holds, and the map."""
        from certifications.services.parcel_map import parcel_boundary_centre

        parcel_name = _s(getattr(parcel, "name", None))

        def _where(event):
            block = _s(event.block_id)
            if not parcel_name:
                return _or_blank(block and f"block {block}")
            return (f"{parcel_name}, block {block}" if block else parcel_name), VALUE

        rows = [_shared(events, "b", "Parcel and block", _where)]

        def _plss(event):
            parts = [
                ("Section", _s(event.mtrs_section)),
                ("Township", _s(event.mtrs_township)),
                ("Range", _s(event.mtrs_range)),
                ("Meridian", _s(event.mtrs_base_meridian)),
            ]
            held = [f"{label} {value}" for label, value in parts if value]
            return (", ".join(held), VALUE) if held else ("", VALUE)

        plss = _shared(events, "b", "Section, township and range", _plss)
        parcel_plss = _s(getattr(parcel, "section_township_range", None))
        if plss.text:
            rows.append(plss)
        elif parcel_plss:
            rows.append(Row("b", "Section, township and range", f"{parcel_plss} (on the parcel)"))
        else:
            centre = parcel_boundary_centre(parcel) if parcel is not None else None
            if centre is not None:
                rows.append(
                    Row(
                        "b",
                        "GPS coordinates",
                        f"{centre[0]:.6f}, {centre[1]:.6f} (centre of the parcel boundary drawn in Trazo)",
                    )
                )
            else:
                rows.append(Row("b", "Section, township and range, or GPS coordinates", NOT_RECORDED, BLANK))

        rows.append(Row("b", "Map", map_text(parcel_name, mapped), VALUE if mapped else BLANK))
        return rows

    @staticmethod
    def _date_row(events) -> Row:
        """(c)'s day, read from every line like any other shared fact: a tank whose lines were
        corrected to different days prints each line's day rather than line 1's alone."""

        def getter(event):
            day = _day(event.date)
            return (day.isoformat(), VALUE) if day else (NOT_RECORDED, BLANK)

        return _shared(events, "c", "Date", getter)

    @staticmethod
    def _time_rows(events, date_row) -> list:
        """(c): the day, and the start and stop clock times as typed."""
        rows = [date_row]

        def _when(attr):
            def getter(event):
                if getattr(event, "time_not_recorded", False):
                    return f"time {NOT_ON_SOURCE_RECORD.lower()}", NOT_ON_SOURCE
                # Each line against its OWN day, so a time on another day says which day.
                return _or_blank(_clock(getattr(event, attr), _day(event.date)))

            return getter

        rows.append(_shared(events, "c", "Start time", _when("application_start")))
        rows.append(_shared(events, "c", "Stop time", _when("application_end")))
        return rows

    @staticmethod
    def _wind(event):
        text = wind_text(event, _method_label)
        if text is None:
            return NOT_RECORDED, BLANK
        reading = _s(event.wind_from) or event.wind_speed_mph is not None
        if conditions_not_applicable(event) and not reading:
            return text, NOT_APPLICABLE
        if "not recorded" in text:
            return text, BLANK
        return text, VALUE

    @staticmethod
    def _temperature(event):
        text = air_temperature_text(event, _method_label)
        if text is None:
            return NOT_RECORDED, BLANK
        if event.air_temperature_f is None:
            return text, NOT_APPLICABLE
        return text, VALUE

    @staticmethod
    def _crop(events, history, parcel):
        """(j): the season's crop, and the variety the record or the block's crop row names."""
        crop = _s(getattr(getattr(history, "product", None), "name", None)) or _s(
            getattr(getattr(history, "crop_type", None), "name", None)
        )

        def getter(event):
            variety = _s(event.variety)
            source = ""
            if not variety and parcel is not None and _s(event.block_id):
                block = _s(event.block_id).lower()
                for planted in parcel.planned_crops.all():
                    if _s(planted.block_name).lower() == block and _s(planted.variety):
                        variety = _s(planted.variety)
                        source = f" (block {_s(event.block_id)} on the parcel's crop list)"
                        break
            if not crop:
                return (f"variety {variety}{source}", VALUE) if variety else (NOT_RECORDED, BLANK)
            return (f"{crop}, variety {variety}{source}" if variety else crop), VALUE

        return _shared(events, "j", "Crop or site", getter)

    @staticmethod
    def _area(event):
        value = _s(event.area) or _num(getattr(event, "area_numeric", None))
        display, original = _area_for_pur(value, _s(event.area_unit))
        if not display:
            return NOT_RECORDED, BLANK
        return (f"{display} ({original} as recorded)" if original else display), VALUE

    @staticmethod
    def _total(volume, unit):
        volume = _s(volume)
        if not volume:
            return "", ""
        return volume, volume_unit_symbol(_s(unit))

    def _per_acre(self, event, volume, unit, area_value, area_unit) -> Row:
        """(g): the declared rate as recorded, else the total over the acres, labelled as worked out."""
        rate = _num(getattr(event, "application_rate", None)) if event is not None else ""
        rate_unit = _s(getattr(event, "application_rate_unit", None)) if event is not None else ""
        if rate:
            label = _RATE_LABEL.get(rate_unit, rate_unit)
            return Row("g", "Per acre", f"{rate} {label}".strip() if label else f"{rate} (unit not recorded)")
        try:
            amount = float(volume) if volume else None
        except ValueError:
            amount = None
        acres = _acres(area_value, area_unit)
        if amount is not None and acres and unit:
            return Row("g", "Per acre", f"{amount / acres:.2f} {unit}/acre, worked out from the total and the acres")
        if amount is not None and unit and _s(area_unit).lower() in ("sq_ft", "sqft", "square_feet"):
            try:
                thousands = float(area_value) / 1000.0
            except (TypeError, ValueError):
                thousands = 0
            if thousands:
                return Row(
                    "g",
                    "Per 1,000 sq ft",
                    f"{amount / thousands:.2f} {unit}/1,000 sq ft, worked out from the total and the area",
                )
        return Row("g", "Per acre", NOT_RECORDED, BLANK)

    def _product_line(self, event, area_value, area_unit) -> ProductLine:
        volume, unit = self._total(_s(event.volume) or _num(event.volume_numeric), event.volume_unit)
        role = "adjuvant" if event.tank_mix_role == "adjuvant" else "product"
        if getattr(event, "concentration_not_recorded", False):
            concentration = Row("h", "Concentration as recorded", NOT_ON_SOURCE_RECORD, NOT_ON_SOURCE)
        else:
            concentration = Row("h", "Concentration as recorded", *_or_blank(event.concentration))
        epa = _s(event.epa_registration_number)
        return ProductLine(
            number=_line_number(event),
            role=role,
            event_id=event.pk,
            name=Row("d", "Product name", *_or_blank(event.commercial_name)),
            epa=Row("d", "EPA Reg. No.", *_or_blank(epa)),
            total=Row("f", "Total applied", *_or_blank(f"{volume} {unit}".strip() if volume else "")),
            per_acre=self._per_acre(event, volume, unit, area_value, area_unit),
            concentration=concentration,
            pests=Row("i", "Pests targeted", *_or_blank(event.target_pest_disease)),
        )

    def _partner_lines(self, event, area_value, area_unit) -> list:
        """Products an older record lists in `tank_mix_partners`: printed as stored, never split."""
        lines = []
        for index, partner in enumerate(getattr(event, "tank_mix_partners", None) or [], start=1):
            if not isinstance(partner, dict):
                continue
            name, epa, vol = (_s(partner.get(k)) for k in ("commercial_name", "epa_registration_number", "volume"))
            if not (name or epa or vol):
                continue
            unit = volume_unit_symbol(_s(partner.get("volume_unit"))) if vol else ""
            lines.append(
                ProductLine(
                    number=f"{_line_number(event)}.{index}",
                    role="listed with",
                    event_id=event.pk,
                    name=Row("d", "Product name", *_or_blank(name)),
                    epa=Row("d", "EPA Reg. No.", *_or_blank(epa)),
                    total=Row("f", "Total applied", *_or_blank(f"{vol} {unit}".strip() if vol else "")),
                    per_acre=self._per_acre(None, vol, unit, area_value, area_unit),
                    concentration=Row("h", "Concentration as recorded", NOT_RECORDED, BLANK),
                    pests=Row("i", "Pests targeted", NOT_RECORDED, BLANK),
                )
            )
        return lines

    @staticmethod
    def _applicator_rows(events) -> list:
        """(l): the applicator copies on the record, and who made the application."""

        def field_of(attr):
            return lambda event: _or_blank(getattr(event, attr, None))

        def licensed(event):
            # (l) asks for "the licensed applicator's full name". A name copied from a profile with
            # no license number is not a licensed applicator, so it never prints bare in that row.
            name = _s(event.applicator_name)
            if name and not _s(event.applicator_certification):
                return f"{name} (no license number on the record)", BLANK
            return _or_blank(name)

        return [
            _shared(events, "l", "Licensed applicator", licensed),
            _shared(events, "l", "Applicator license number", field_of("applicator_certification")),
            _shared(events, "l", "Applicator address", field_of("applicator_address")),
            _shared(events, "l", "Applicator phone", field_of("applicator_phone")),
            _shared(events, "l", "Individual(s) making the application", field_of("performed_by")),
        ]

    @staticmethod
    def _firm_rows(events) -> list:
        """(n): the commercial firm, when the record marks or names one."""
        commercial = any(
            e.applied_by_pcb or _s(e.pcb_name) or _s(getattr(e, "commercial_firm_address", "")) for e in events
        )
        if not commercial:
            return [
                Row(
                    "n", "Commercial firm", "The record does not mark this as a commercial application.", NOT_APPLICABLE
                )
            ]
        return [
            _shared(events, "n", "Firm name", lambda e: _or_blank(e.pcb_name)),
            _shared(events, "n", "Firm address", lambda e: _or_blank(getattr(e, "commercial_firm_address", ""))),
        ]

    def _build_pass(self, number, events, operator_rows, mapped_parcel_ids, entered) -> ApplicationPass:
        first = events[0]
        history = first.history
        parcel = getattr(history, "parcel", None)
        days = list(dict.fromkeys(_day(e.date) for e in events))
        date_row = self._date_row(events)
        area_value = _s(first.area) or _num(getattr(first, "area_numeric", None))
        area_unit = _s(first.area_unit)
        mapped = parcel is not None and parcel.pk in mapped_parcel_ids

        record = ApplicationPass(
            number=number,
            events=events,
            parcel=parcel,
            applied_on=days[0] if len(days) == 1 else None,
            applied_text=date_row.text,
            mapped=mapped,
        )
        record.before = list(operator_rows) + self._location_rows(events, parcel, mapped)
        record.before += self._time_rows(events, date_row)
        if len(days) > 1:
            record.notes.append(
                "The lines of this tank are recorded on different days; item (c) prints each line's day."
            )

        for event in events:
            record.products.append(self._product_line(event, area_value, area_unit))
            record.products.extend(self._partner_lines(event, area_value, area_unit))

        carrier = _shared(events, "h", "Output volume (carrier)", lambda e: _or_blank(carrier_text(e)))
        if carrier.status == BLANK:
            carrier.status = ALTERNATIVE
        record.after = [
            _shared(events, "e", "Wind", self._wind),
            _shared(events, "e", "Air temperature", self._temperature),
            carrier,
            self._crop(events, history, parcel),
            _shared(events, "k", "Apparatus license plate", lambda e: _or_blank(e.apparatus_license_plate)),
            *self._applicator_rows(events),
            _shared(events, "m", "Acres treated", self._area),
            *self._firm_rows(events),
        ]

        days = [(e, entered.get(e.pk)) for e in events]
        entered_texts = {d.isoformat() if d else "entry date not recorded" for _e, d in days}
        if len(entered_texts) == 1:
            entered_text = entered_texts.pop()
        else:
            entered_text = "; ".join(
                f"line {_line_number(e)}: {d.isoformat() if d else 'entry date not recorded'}" for e, d in days
            )
        record.entered = entered_text

        for event in events:
            extra = event.extra_data if isinstance(event.extra_data, dict) else {}
            free_text = _s(extra.get("tank_mix"))
            if free_text and not (event.tank_mix_partners or []):
                record.notes.append(f"Tank partners named in the record's notes, not itemised: {free_text}.")
            if extra.get("is_summary") is True or _s(event.time_period):
                record.notes.append(
                    "This record summarises a period of applications; the rule asks for a record of each one."
                )
        return record

    def build(self) -> list:
        """The passes of the period, in date order."""
        if self._built is not None:
            return self._built
        records = self._records()
        groups = self._group(records)
        groups.sort(
            key=lambda lines: (
                _day(lines[0].date) or date.min,
                _s(getattr(getattr(lines[0].history, "parcel", None), "name", None)).lower(),
                _s(lines[0].block_id).lower(),
                lines[0].pk,
            )
        )
        parcels = self.parcels(records)
        mapped = {p.pk for p in parcels if _map_drawing(p) is not None}
        operator_rows = self._operator_rows()
        entered = self._entered_on(records)
        self._built = [
            self._build_pass(number, lines, operator_rows, mapped, entered)
            for number, lines in enumerate(groups, start=1)
        ]
        self._note_one_application_on_several_blocks(self._built)
        return self._built

    @staticmethod
    def _note_one_application_on_several_blocks(passes) -> None:
        """A spray logged once on several blocks is one record per block (`multi_target`), so it
        prints as one block per parcel. Without a note, four blocks sprayed 07:30 to 13:00 read as
        four applications each lasting the whole window. Each such block names its siblings."""
        by_group = {}
        for record in passes:
            for group in {e.application_group for e in record.events if getattr(e, "application_group", None)}:
                by_group.setdefault(group, []).append(record)
        for record in passes:
            siblings = {}
            for group in {e.application_group for e in record.events if getattr(e, "application_group", None)}:
                for other in by_group.get(group, []):
                    siblings[other.number] = other
            if len(siblings) < 2:
                continue
            ordered = [siblings[n] for n in sorted(siblings)]
            numbers = [str(other.number) for other in ordered]
            listed = ", ".join(numbers[:-1]) + f" and {numbers[-1]}"
            places = []
            for other in ordered:
                name = _s(getattr(other.parcel, "name", None)) or "parcel not recorded"
                if name not in places:
                    places.append(name)
            note = (
                f"Logged as one application on {len(ordered)} blocks, printed as applications {listed} "
                f"({', '.join(places)})."
            )
            # `application_group` is fixed at creation, but each block's date and times can be
            # corrected alone afterwards. The note claims sameness only where the records still hold it.
            events = [e for other in ordered for e in other.events]
            if len({_day(e.date) for e in events}) > 1:
                note += " The blocks' dates were later recorded differently; item (c) prints each block's own day."
            else:
                windows = {(e.application_start, e.application_end) for e in events}
                if len(windows) == 1 and any(next(iter(windows))):
                    note += " The start and stop times are the whole application's, not this block's alone."
            record.notes.append(note)

    @staticmethod
    def parcels(records) -> list:
        """The parcels the records were applied on, in first-use order."""
        seen = {}
        for record in records:
            parcel = getattr(record.history, "parcel", None)
            if parcel is not None and parcel.pk not in seen:
                seen[parcel.pk] = parcel
        return list(seen.values())

    # ------------------------------------------------------------------
    def summary(self) -> dict:
        """The preview the app reads: counts and, per pass, which item letters are blank."""
        passes = self.build()
        parcels = []
        for record in passes:
            if record.parcel is not None and record.parcel not in parcels:
                parcels.append((record.parcel, record.mapped))
        return {
            "establishment_id": self.establishment.id,
            "establishment_name": self.establishment.name,
            "rule": RULE,
            "period_start": self.start.isoformat(),
            "period_end": self.end.isoformat(),
            "pass_count": len(passes),
            "product_line_count": sum(len(p.products) for p in passes),
            "passes_with_blank_items": sum(1 for p in passes if p.blank_items()),
            "parcels_without_map": [parcel.name for parcel, mapped in parcels if not mapped],
            "passes": [
                {
                    "number": p.number,
                    "event_id": p.events[0].pk,
                    "event_type": CHEMICAL_EVENT_TYPE,
                    "event_ids": [e.pk for e in p.events],
                    "parcel_id": getattr(p.parcel, "pk", None),
                    "parcel_name": _s(getattr(p.parcel, "name", None)),
                    "block": _s(p.events[0].block_id),
                    # One day, or "" when the lines differ; `event_days` then lists each day.
                    "event_date": p.applied_on.isoformat() if p.applied_on else "",
                    "event_days": (
                        list(dict.fromkeys(_day(e.date).isoformat() for e in p.events if e.date))
                        if p.applied_on is None
                        else []
                    ),
                    "products": [line.name.text for line in p.products],
                    "blank_items": p.blank_items(),
                }
                for p in passes
            ],
        }

    # ------------------------------------------------------------------
    #: CSV columns: (key, header). One row per product line; a pass's own columns repeat on each of
    #: its lines and the "Pass" column ties them, so no cell is blank by layout.
    CSV_COLUMNS = (
        ("pass", "Pass"),
        ("line", "Line in pass"),
        ("a_name", "(a) Person for whom applied"),
        ("a_address", "(a) Address"),
        ("b_parcel", "(b) Parcel and block"),
        ("b_location", "(b) Section, township and range, or GPS"),
        ("b_map", "(b) Map"),
        ("c_date", "(c) Date"),
        ("c_start", "(c) Start time"),
        ("c_stop", "(c) Stop time"),
        ("d_product", "(d) Product name"),
        ("d_epa", "(d) EPA registration number"),
        ("e_wind", "(e) Wind"),
        ("e_temperature", "(e) Air temperature"),
        ("f_total", "(f) Total amount applied"),
        ("g_per_acre", "(g) Amount per acre"),
        ("h_concentration", "(h) Concentration as recorded"),
        ("h_carrier", "(h) Output volume (carrier)"),
        ("i_pests", "(i) Pests targeted"),
        ("j_crop", "(j) Crop or site"),
        ("k_plate", "(k) Apparatus license plate"),
        ("l_applicator", "(l) Licensed applicator"),
        ("l_license", "(l) Applicator license number"),
        ("l_address", "(l) Applicator address"),
        ("l_phone", "(l) Applicator phone"),
        ("l_individuals", "(l) Individual(s) making the application"),
        ("m_acres", "(m) Acres treated"),
        ("n_firm", "(n) Commercial firm"),
        ("n_address", "(n) Firm address"),
        ("entered", "(2) Record entered in Trazo (Pacific time)"),
        ("blank_items", "Items not on this record"),
        ("notes", "Notes"),
    )

    @staticmethod
    def _by_label(rows, item, label):
        for row in rows:
            if row.item == item and row.label == label:
                return row.text
        return ""

    def csv_rows(self) -> list:
        rows = []
        for record in self.build():
            pass_rows = record.before + record.after
            location = next(
                (r.text for r in record.before if r.item == "b" and r.label not in ("Parcel and block", "Map")), ""
            )
            firm = next(
                (r.text for r in record.after if r.item == "n" and r.label in ("Firm name", "Commercial firm")), ""
            )
            shared = {
                "pass": record.number,
                "a_name": self._by_label(pass_rows, "a", "Name"),
                "a_address": self._by_label(pass_rows, "a", "Address"),
                "b_parcel": self._by_label(pass_rows, "b", "Parcel and block"),
                "b_location": location,
                "b_map": map_text(_s(getattr(record.parcel, "name", None)), record.mapped, "csv"),
                "c_date": self._by_label(pass_rows, "c", "Date"),
                "c_start": self._by_label(pass_rows, "c", "Start time"),
                "c_stop": self._by_label(pass_rows, "c", "Stop time"),
                "e_wind": self._by_label(pass_rows, "e", "Wind"),
                "e_temperature": self._by_label(pass_rows, "e", "Air temperature"),
                "h_carrier": self._by_label(pass_rows, "h", "Output volume (carrier)"),
                "j_crop": self._by_label(pass_rows, "j", "Crop or site"),
                "k_plate": self._by_label(pass_rows, "k", "Apparatus license plate"),
                "l_applicator": self._by_label(pass_rows, "l", "Licensed applicator"),
                "l_license": self._by_label(pass_rows, "l", "Applicator license number"),
                "l_address": self._by_label(pass_rows, "l", "Applicator address"),
                "l_phone": self._by_label(pass_rows, "l", "Applicator phone"),
                "l_individuals": self._by_label(pass_rows, "l", "Individual(s) making the application"),
                "m_acres": self._by_label(pass_rows, "m", "Acres treated"),
                "n_firm": firm,
                "n_address": self._by_label(pass_rows, "n", "Firm address"),
                "entered": record.entered,
                "blank_items": " ".join(f"({letter})" for letter in record.blank_items()),
                "notes": " ".join(record.notes),
            }
            for line in record.products:
                row = dict(shared)
                row.update(
                    {
                        "line": f"{line.number} ({line.role})",
                        "d_product": line.name.text,
                        "d_epa": line.epa.text,
                        "f_total": line.total.text,
                        "g_per_acre": line.per_acre.text,
                        "h_concentration": line.concentration.text,
                        "i_pests": line.pests.text,
                    }
                )
                rows.append(row)
        return rows

    def to_csv(self) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        # The marking is the FIRST row of a fabricated farm's file, above everything it could be
        # scrolled past (history/tests/test_specimen_marking.py).
        if is_specimen(self.establishment):
            writer.writerow([SPECIMEN_LINE])
        writer.writerow([f"Pesticide application records for {self.establishment.name}, {self.period_label}"])
        writer.writerow([HEADER_STATEMENT])
        passes = self.build()
        writer.writerow(
            [
                f"Applications: {len(passes)}. Product lines: {sum(len(p.products) for p in passes)}. "
                "Pesticide, fungicide and herbicide records; fertilizer records are not included."
            ]
        )
        writer.writerow([])
        writer.writerow([header for _key, header in self.CSV_COLUMNS])
        for row in self.csv_rows():
            writer.writerow([row.get(key, "") for key, _header in self.CSV_COLUMNS])
        return buffer.getvalue().encode("utf-8-sig")

    # ------------------------------------------------------------------
    def to_pdf(self) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.lib.utils import simpleSplit
        from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        from certifications.services.parcel_map import parcel_map_caption

        base = getSampleStyleSheet()
        styles = {
            "title": ParagraphStyle("wa_t", parent=base["Title"], fontSize=15, leading=18, spaceAfter=2),
            "sub": ParagraphStyle("wa_s", parent=base["Normal"], fontSize=10, leading=13, alignment=1),
            "body": ParagraphStyle("wa_b", parent=base["Normal"], fontSize=9, leading=11.5, spaceAfter=3),
            "head": ParagraphStyle(
                "wa_h", parent=base["Heading3"], fontSize=10.5, leading=13, spaceBefore=8, spaceAfter=3
            ),
            "cell": ParagraphStyle("wa_c", parent=base["Normal"], fontSize=7.8, leading=9.4),
            "blank": ParagraphStyle(
                "wa_cb", parent=base["Normal"], fontSize=7.8, leading=9.4, textColor=colors.HexColor("#5D4037")
            ),
            "cell_head": ParagraphStyle(
                "wa_ch", parent=base["Normal"], fontSize=7.8, leading=9.4, fontName="Helvetica-Bold"
            ),
            "foot": ParagraphStyle("wa_f", parent=base["Normal"], fontSize=8.2, leading=10, spaceBefore=2),
            "specimen": ParagraphStyle(
                "wa_sp", parent=base["Normal"], fontSize=9, leading=11.5, textColor=colors.HexColor("#B71C1C")
            ),
        }

        def p(text, style="cell"):
            return Paragraph(escape(str(text or "")), styles[style])

        def cell(row):
            if row.status in _BLANK_STATUSES or row.status == ALTERNATIVE:
                return Paragraph(f"<i>{escape(row.text)}</i>", styles["blank"])
            return p(row.text)

        grid = TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9E9E9E")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
        head_grid = TableStyle(grid.getCommands() + [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9"))])
        labels = dict(ITEMS)

        def item_table(rows):
            data = [[p(f"({row.item}) {row.label}", "cell_head"), cell(row)] for row in rows]
            table = Table(data, colWidths=[2.15 * inch, 5.15 * inch])
            table.setStyle(grid)
            return table

        def products_table(lines):
            data = [
                [
                    p("Line", "cell_head"),
                    p(f"(d) {labels['d']}", "cell_head"),
                    p(f"(f) {labels['f']}", "cell_head"),
                    p(f"(g) {labels['g']}", "cell_head"),
                    p(f"(h) {labels['h']}", "cell_head"),
                    p(f"(i) {labels['i']}", "cell_head"),
                ]
            ]
            for line in lines:
                name = line.name.text if not line.name.is_blank else f"Product name: {line.name.text}"
                product = Paragraph(
                    f"{escape(name)}<br/>EPA Reg. No.: "
                    + (f"<i>{escape(line.epa.text)}</i>" if line.epa.is_blank else escape(line.epa.text)),
                    styles["cell"],
                )
                data.append(
                    [
                        p(f"{line.number} {line.role}"),
                        product,
                        cell(line.total),
                        cell(line.per_acre),
                        cell(line.concentration),
                        cell(line.pests),
                    ]
                )
            table = Table(
                data,
                colWidths=[0.62 * inch, 1.9 * inch, 1.0 * inch, 1.38 * inch, 1.2 * inch, 1.2 * inch],
                repeatRows=1,
            )
            table.setStyle(head_grid)
            return table

        story = []
        specimen = is_specimen(self.establishment)
        if specimen:
            story.append(Paragraph(f"<b>{escape(SPECIMEN_TITLE)}</b>. {escape(SPECIMEN_BODY)}", styles["specimen"]))
            story.append(Spacer(1, 4))
        story.append(p("Pesticide application records", "title"))
        story.append(p(f"{self.establishment.name}, {self.period_label}", "sub"))
        story.append(Spacer(1, 6))
        story.append(p(self.header_text(), "body"))
        passes = self.build()
        story.append(
            p(
                f"Applications: {len(passes)}. Product lines: {sum(len(x.products) for x in passes)}. "
                "Pesticide, fungicide and herbicide records logged for this farm with a date in the period; "
                "fertilizer records are not included. A tank prints once, with each product on its own line. "
                "Each application shows the day it was made and the day its record was entered in Trazo "
                "(WAC 16-228-1320(2)), in Pacific time. A blank item reads Not recorded, Not on the source "
                "record (the operator marked it so), or Not applicable (method) for wind and temperature where "
                "WAC 16-228-1320(1)(e) does not ask for them.",
                "body",
            )
        )
        if not passes:
            story.append(p("No pesticide application is recorded for this farm in this period.", "body"))

        for record in passes:
            parcel_name = _s(getattr(record.parcel, "name", None)) or "parcel not recorded"
            block = _s(record.events[0].block_id)
            heading = f"Application {record.number}: {record.applied_text}, "
            heading += f"{parcel_name}{f', block {block}' if block else ''}"
            if record.is_tank:
                heading += f". One tank, {len(record.products)} products"
            block_flow = [
                p(heading, "head"),
                item_table(record.before),
                Spacer(1, 3),
                products_table(record.products),
                Spacer(1, 3),
                item_table(record.after),
                p(
                    f"(2) Applied {record.applied_text}; " f"record entered in Trazo {record.entered} (Pacific time).",
                    "foot",
                ),
            ]
            for note in record.notes:
                block_flow.append(p(note, "foot"))
            block_flow.append(Paragraph(f"<b>{escape(record.blank_line())}</b>", styles["foot"]))
            story.append(KeepTogether(block_flow))

        # Field maps, WAC 16-228-1320(1)(b): one page per parcel whose boundary can be drawn.
        # The same predicate the (b) rows were written from (`record.mapped`, from `_map_drawing`).
        parcels = []
        for record in passes:
            if record.parcel is not None and all(record.parcel != seen for seen, _m in parcels):
                parcels.append((record.parcel, record.mapped))
        unmapped = [parcel.name for parcel, mapped in parcels if not mapped]
        for parcel, mapped in parcels:
            drawing = _map_drawing(parcel) if mapped else None
            if drawing is None:
                continue
            story.append(PageBreak())
            story.append(p(f"Field map: {parcel.name}", "head"))
            story.append(
                p(
                    "WAC 16-228-1320(1)(b) asks that a field of one acre or more be located on the map on the "
                    "department's adopted form. This is a not-to-scale schematic drawn from the parcel boundary "
                    "recorded in Trazo, with adjoining land use as recorded. It is not a survey and not the "
                    "adopted form's map.",
                    "body",
                )
            )
            story.append(drawing)
            story.append(p(parcel_map_caption(parcel), "body"))
        if unmapped:
            story.append(
                p(
                    f"No parcel boundary that can be drawn is recorded in Trazo for: {', '.join(unmapped)}. "
                    "No map is included for "
                    f"{'it' if len(unmapped) == 1 else 'them'}.",
                    "body",
                )
            )

        footer_first = f"Pesticide application records for {self.establishment.name}, {self.period_label}."

        # The statement on every page, not the first alone: a page of this is printed and handed
        # over on its own.
        footer_lines = [f"{footer_first} Page {{page}}."] + simpleSplit(HEADER_STATEMENT, "Helvetica", 6.5, 7.3 * inch)

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 6.5)
            canvas.setFillColor(colors.HexColor("#424242"))
            for index, line in enumerate(footer_lines):
                canvas.drawString(0.6 * inch, (0.45 - 0.11 * index) * inch, line.replace("{page}", str(doc.page)))
            canvas.restoreState()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.6 * inch,
            rightMargin=0.6 * inch,
            topMargin=0.6 * inch,
            bottomMargin=0.7 * inch,
            title=f"Pesticide application records: {self.establishment.name}, {self.period_label}",
        )
        furniture = specimen_page_callback(letter, base_callback=footer, specimen=specimen)
        doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
        return buffer.getvalue()
