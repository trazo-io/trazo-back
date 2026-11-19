"""The raw-manure harvest interval: one reading of 7 CFR 205.203(c)(1) for every surface.

Paragraphs (c)(1)(ii) and (iii) set a FLOOR: raw manure is incorporated "not less than"
120 days before harvest when the edible portion touches the soil, and "not less than"
90 days when it does not. A longer wait satisfies either paragraph, so the only stored
interval that can be wrong is one SHORTER than the crop's floor. A farm that keeps 120
days on a tree crop (walnuts swept from the orchard floor, avocados collected from the
ground) is compliant and must be able to say so.

Which floor applies is the crop's `CropType.has_soil_contact` flag and nothing else.
Until 2026-11 the save path read the flag while the audit export also matched crop names
against a keyword list, and on a freshly seeded database the flag was True for every
crop. Apples were then refused 90 days on the form, accepted at 120, and printed in the
inspector's dossier as "MISMATCH, crop requires 90-day". Every reader asks this module
now: the serializer, the model's clean(), the harvest-side check and the audit export.
"""

from __future__ import annotations

SOIL_CONTACT_MINIMUM_DAYS = 120  # § 205.203(c)(1)(ii)
NO_SOIL_CONTACT_MINIMUM_DAYS = 90  # § 205.203(c)(1)(iii)

SOIL_CONTACT_CITE = "§ 205.203(c)(1)(ii)"
NO_SOIL_CONTACT_CITE = "§ 205.203(c)(1)(iii)"


def edible_part_touches_soil(crop_type) -> bool | None:
    """The crop's class under § 205.203(c)(1), or None when no crop is known."""
    if crop_type is None:
        return None
    flag = getattr(crop_type, "has_soil_contact", None)
    return None if flag is None else bool(flag)


def minimum_interval_days(crop_type) -> int:
    """The floor for this crop. An unknown crop gets 120, which satisfies both paragraphs."""
    if edible_part_touches_soil(crop_type) is False:
        return NO_SOIL_CONTACT_MINIMUM_DAYS
    return SOIL_CONTACT_MINIMUM_DAYS


def minimum_interval_cite(crop_type) -> str:
    if edible_part_touches_soil(crop_type) is False:
        return NO_SOIL_CONTACT_CITE
    return SOIL_CONTACT_CITE


def gathered_from_ground(crop_type) -> bool:
    """A crop on the 90-day floor whose harvest is swept from the ground (`CropType.harvested_from_ground`).

    The kernel of a walnut or an almond does not touch the soil, so (c)(1)(iii) sets 90 days; the shell lies on
    the orchard floor, and a certifier can read that as soil contact under (c)(1)(ii), 120 days. The floor stays
    90 and nothing is refused; an interval under 120 is printed for the certifier to confirm.
    """
    return edible_part_touches_soil(crop_type) is False and bool(getattr(crop_type, "harvested_from_ground", False))


def interval_days(value) -> int | None:
    """A stored choice ("120", "90", legacy "120_days") as days; None for "na" or blank."""
    raw = str(value or "").split("_")[0]
    return int(raw) if raw.isdigit() else None


def below_minimum(value, crop_type) -> bool:
    """True only when the stored interval is SHORTER than the crop's floor."""
    days = interval_days(value)
    return days is not None and days < minimum_interval_days(crop_type)


def below_minimum_message(crop_type) -> str:
    """The refusal a grower reads when a known soil-contact crop is given 90 days."""
    name = getattr(crop_type, "name", "") or "This crop"
    return (
        f"{name}: the edible part touches the soil, so 7 CFR 205.203(c)(1)(ii) requires at least "
        f"{SOIL_CONTACT_MINIMUM_DAYS} days between incorporating raw manure and harvest. Choose "
        f"{SOIL_CONTACT_MINIMUM_DAYS} days, or record the manure as composted if it meets § 205.203(c)(2)."
    )


#: A stable code for the refusal, so a screen can word it in the reader's language. The sentence
#: above is English, and a Spanish grower read it after the field's Spanish label (recordkeeping
#: checklist run 2026-11-16, VID-07).
BELOW_MINIMUM_CODE = "manure_below_floor"


def below_minimum_error(crop_type) -> dict:
    """The refusal as a DRF error body: the English sentence under the field, and its code with
    the values a translation needs under `error_codes` (a dict, so error readers that list a
    body's field errors pass over it)."""
    return {
        "manure_harvest_interval": [below_minimum_message(crop_type)],
        "error_codes": {
            "manure_harvest_interval": {
                "code": BELOW_MINIMUM_CODE,
                "crop": getattr(crop_type, "name", "") or "",
                "days": str(SOIL_CONTACT_MINIMUM_DAYS),
            }
        },
    }
