"""
"Not on the source record": the operator's statement that a spray's paper record does not show a
fact, instead of a value nobody observed (overall review 2026-11, OV-FJ-C12; pilot rehearsal
findings 3 and 8).

A grower typing a season of sprays in from a paper log often has a day but no clock time, and a
product name but no concentration. The form required both, so the only way through was to look up
a label or invent a value, and an invented value prints into the certifier packet as if it had
been observed. § 205.103(b) records must disclose the activity accurately; a blank that SAYS it is
a blank does, a plausible number does not.

Two flags on `ChemicalEvent`, and ONE rule for both: the flag or the value, never the two together.

* `concentration_not_recorded`: the concentration stays empty.
* `time_not_recorded`: the record keeps its DATE. The clock is stored at noon UTC, which is the
  importer's encoding for a day with no time (`cogpro_import._as_event_datetime`, same calendar
  day in every zone from UTC-11 to UTC+11). The CA start and completion times (DPR boxes 17-18)
  are clock times too, so they stay empty as well. Every reader that would print a time prints
  NOT_ON_SOURCE_RECORD instead, never the noon placeholder.

"A day with no time" is decided by the SHAPE of what the operator sent, never by the clock value
it parses to: a bare `YYYY-MM-DD` is a day; anything with a time part is a stated time, including
`T12:00` and `T00:00`. A clock-value test cannot tell a real 12:00 UTC application (07:00 in the
east) from the placeholder, so a record sprayed at that hour could never be corrected to it.

The serializer, the model's `clean()` and the correction path all read the rule from here.
"""

from __future__ import annotations

import re
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Optional

#: What every printed surface says in place of the value. Distinct from a plain blank, which keeps
#: its own wording ("—", "not recorded"): a blank says nothing was entered, this says the operator
#: looked and the source record does not show it.
NOT_ON_SOURCE_RECORD = "Not on the source record"

#: A day and nothing else, as the operator sent it.
_DAY_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CONCENTRATION_CONFLICT = (
    "The concentration is marked as not on the source record. Leave it blank, or untick that box "
    "and enter the concentration."
)
WINDOW_CONFLICT = (
    "The time is marked as not on the source record. Leave the start and completion times blank, "
    "or untick that box and enter them."
)
CLOCK_CONFLICT = (
    "The time is marked as not on the source record, so the date cannot carry a clock time. Send "
    "the day alone, or untick that box."
)
#: Clearing the time mark: the stored clock is the noon placeholder, so the request that clears it
#: must state the time from the source record. Shared by an edit and a correction.
UNMARK_NEEDS_A_TIME = (
    "This record holds no clock time; its day is stored without one. Correct the date to the date "
    "and time on the source record, and that removes this mark."
)


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _utc(when):
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def is_day_only(raw) -> bool:
    """Whether the operator sent a day and no time, judged by the INPUT's shape, never its value.

    A bare `YYYY-MM-DD` string (or a date object) is a day. Anything carrying a time part,
    `T12:00` and `T00:00` included, or a datetime object, is a stated clock time.
    """
    if isinstance(raw, datetime):
        return False
    if isinstance(raw, date_type):
        return True
    return isinstance(raw, str) and bool(_DAY_ONLY.match(raw.strip()))


def day_without_time(when):
    """The stored form of a day with no clock time: noon UTC on the same calendar day."""
    from history.services.cogpro_import import _as_event_datetime

    return _as_event_datetime(_utc(when).date())


def conflicts(
    *,
    concentration_not_recorded,
    concentration,
    time_not_recorded,
    application_start,
    application_end,
    date_input=None,
) -> dict:
    """{field: message} for every place a flag and a value were given together.

    `date_input` is the date AS SENT (the raw request value), checked only when the request carried
    one: under the time mark it must be a bare day. A stored date is normalised to the placeholder
    by the caller, never refused.
    """
    errors = {}
    if concentration_not_recorded and _present(concentration):
        errors["concentration"] = CONCENTRATION_CONFLICT
    if time_not_recorded:
        for key, value in (("application_start", application_start), ("application_end", application_end)):
            if value is not None and value != "":
                errors[key] = WINDOW_CONFLICT
        if date_input is not None and not is_day_only(date_input):
            errors["date"] = CLOCK_CONFLICT
    return errors


def concentration_text(event) -> Optional[str]:
    """The concentration as a document prints it: the phrase when flagged, else the stored value."""
    if getattr(event, "concentration_not_recorded", False):
        return NOT_ON_SOURCE_RECORD
    return getattr(event, "concentration", None)


def date_text(when) -> str:
    """A flagged record's date for a line of text: the day, and the phrase in place of a time."""
    return f"{_utc(when).date().isoformat()} (time {NOT_ON_SOURCE_RECORD.lower()})"
