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

The serializer, the model's `clean()` and the correction path all read the rule from here.
"""

from __future__ import annotations

from datetime import time, timezone
from typing import Optional

#: What every printed surface says in place of the value. Distinct from a plain blank, which keeps
#: its own wording ("—", "not recorded"): a blank says nothing was entered, this says the operator
#: looked and the source record does not show it.
NOT_ON_SOURCE_RECORD = "Not on the source record"

#: The clock times a day-only value arrives with: midnight (a bare `YYYY-MM-DD` parses to it) and
#: noon (the stored placeholder). Anything else is a clock time somebody stated.
_PLACEHOLDER_CLOCKS = (time(0, 0), time(12, 0))

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


def has_clock_time(when) -> bool:
    """Whether a datetime carries a clock time someone stated (anything but midnight or noon UTC)."""
    if when is None:
        return False
    return _utc(when).time() not in _PLACEHOLDER_CLOCKS


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
    date=None,
) -> dict:
    """{field: message} for every place a flag and a value were given together.

    `date` is checked only when the caller passes it, i.e. when the request carried one: a stored
    date is normalised to the placeholder by the caller, never refused.
    """
    errors = {}
    if concentration_not_recorded and _present(concentration):
        errors["concentration"] = CONCENTRATION_CONFLICT
    if time_not_recorded:
        for key, value in (("application_start", application_start), ("application_end", application_end)):
            if value is not None and value != "":
                errors[key] = WINDOW_CONFLICT
        if has_clock_time(date):
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
