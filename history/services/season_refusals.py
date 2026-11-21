"""The activity form's season refusals, each with a code a screen can word in the reader's language.

The sentences are English, and a Spanish grower read them as they were (recordkeeping checklist run
2026-11-16, VID-07). Each body keeps its English sentence under the key it always had and adds
`error_codes[key] = {"code": ..., <values>}`, the shape `manure_interval.below_minimum_error` set: a dict,
so the screens that list a body's field errors pass over it.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

SEASON_CLOSED = "season_closed"
SEASON_AMBIGUOUS = "season_ambiguous"
NO_OPEN_SEASON = "no_open_season"
SEASON_NOT_ON_PARCEL = "season_not_on_parcel"


def coded(key: str, sentence: str, code: str, **values) -> dict:
    """`{key: [sentence], "error_codes": {key: {"code": code, **values}}}`, every value a string."""
    return {
        key: [sentence],
        "error_codes": {key: {"code": code, **{name: str(value) for name, value in values.items()}}},
    }


class ClosedSeasonRefused(PermissionDenied):
    """A record dated inside a finished season. A 403 whose body is `{"detail": sentence, "error_codes": ...}`.

    `sentence` is the English text alone, for readers that list refusals as text (the operator importer).
    """

    def __init__(self, sentence: str, finish_day):
        self.sentence = sentence
        super().__init__(
            {
                "detail": sentence,
                "error_codes": {"detail": {"code": SEASON_CLOSED, "finish_date": finish_day.isoformat()}},
            }
        )
