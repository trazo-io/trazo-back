"""An organic basis a record may no longer be given (overall review 2026-11-24, M7-I1).

"Transitional - In certification process" was offered as the organic basis of an input on the spray
form, the soil amendment form, a tank's product lines and quick add. It describes the OPERATION (a
farm in its 36 months of conversion), not the input, so a grower on a transitional farm picked it in
good faith. Its stored value is a prohibited-substance answer (`ORGANIC_PROHIBITED_VALUES`, on
purpose), so one pick on a fish fertilizer record moved a certified parcel's § 205.202(b) line from
"No prohibited substance on record in Trazo for the last 36 months" to "In transition, 964 days
remaining".

The value stays a valid STORED answer and its classification is unchanged: a row already holding it
reads as it did, and an edit that leaves it as it is still saves. What is refused is a record being
GIVEN it: on create (a tank's lines included, each is its own record), and on an edit or a correction
that changes the value to it. The refusal says what to pick instead, in the option words the forms
show.

Every write path calls `is_refused_change`: the activity serializers (`refuse_new_refused_basis`),
the correction path (`history/amendments.py`) and the operator intake (`record_intake.py`).
"""

from __future__ import annotations

from rest_framework import serializers

from common.field_registry import ORGANIC_APPROVED_REFUSED_ON_WRITE
from history.services.season_refusals import coded

#: The fields that hold an input's organic basis (`ORGANIC_APPROVED` choices).
ORGANIC_BASIS_FIELDS = ("organic_approved", "amendment_organic_approved")

#: A stable code, so a screen can word the refusal in the reader's language (trazo-app
#: `CODED_MESSAGES`, `apiErrors.organicBasisTransitional`).
TRANSITIONAL_BASIS_REFUSED = "organic_basis_transitional"

TRANSITIONAL_BASIS_SENTENCE = (
    '"Transitional" describes a farm in conversion, not this input, so it is no longer an organic basis. '
    "Choose what shows the input is allowed (OMRI Listed, WSDA Listed, NOP seal on the product label, or "
    'Reviewed and approved by my certifier), "Not yet confirmed" if that is still to be checked, or '
    '"No organic basis: conventional use only" if the input is not allowed on organic land.'
)


def is_refused_change(value, stored=None) -> bool:
    """True when `value` is a basis a record may no longer be given and `stored` is not already it.

    `stored` is the record's current value (None on create). The same value sent back unchanged, as an
    edit form round-trips every field, is not a new write and is never refused.
    """
    return bool(value) and value in ORGANIC_APPROVED_REFUSED_ON_WRITE and value != stored


def refusal(field: str) -> dict:
    """The refusal as a DRF error body: the sentence under the field, its code under `error_codes`."""
    return coded(field, TRANSITIONAL_BASIS_SENTENCE, TRANSITIONAL_BASIS_REFUSED)


def refuse_new_refused_basis(serializer, data, field: str) -> None:
    """Raise the coded refusal when this request gives the record a refused basis.

    Reads the field from the request only: a partial edit that does not send it changes nothing.
    """
    if field not in data:
        return
    instance = getattr(serializer, "instance", None)
    stored = getattr(instance, field, None) if instance is not None else None
    if is_refused_change(data[field], stored):
        raise serializers.ValidationError(refusal(field))
