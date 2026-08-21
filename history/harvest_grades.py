"""One harvest-grade vocabulary, crop-aware, carrying the USDA grade families.

## What was wrong (F5, Calapooia Bend rehearsal, 2026-08-21)

There were TWO vocabularies for one fact, and neither was a grade anyone uses:

  * `ProductionEvent.harvest_quality_grade` offered Export Quality / Grade A / Grade B /
    Grade C / Domestic Market / Processing.
  * `History.quality_grade` — the season header, the lot's own identity — offered a
    DIFFERENT list: Premium / Grade A / Grade B / Standard / Processing.

So a lot header and the picks underneath it could not agree with each other, and the packet
printed both. A previous rehearsal's certifier reviewer found "Premium Grade" on a header
beside "WA Extra Fancy" on the picks and said the obvious thing: *"Grade A is not an apple
grade."* Real packing records read "U.S. No. 1", "U.S. Commercial", "WA Extra Fancy",
"U.S. Fancy" — none of which was offered, so the farmer picked the least-wrong option and the
packet printed a grade the certifier cannot match to the packing record.

## The rule this module encodes

**Crop-aware, never a flat list.** A single list of every USDA grade offers an apple grower
"U.S. Commercial" (an onion grade) and an onion grower "WA Extra Fancy", which is how a wrong
grade reaches a packing record in the first place.

**No grade is better than a wrong grade.** A crop with no USDA standard — hops, pomegranates,
avocados, cotton — gets an EMPTY list and only the free-text escape. Inventing "U.S. No. 1" for
a commodity that has no such standard would be the same defect one level up. The escape is
always offered, for every crop, because private buyer grades and state marks are real and a
farmer must never be forced to state a grade their packing record does not.

**The stored value IS the printed value.** These are display strings, not slugs. The packet's
`_humanize_enum` reproduces anything containing a capital verbatim (that is the 2026-08-20 fix
for `.title()` turning "WA Extra Fancy" into "Wa Extra Fancy"), so what the operator selected is
what the reviewer reads. The legacy slugs stay in the choice tuple so rows written before this
change still render their old label rather than a bare `grade_a`.

⚠️ Mirrored in `trazo-app/src/config/harvestGrades.ts`, which is what the two forms render.
`history/tests/test_harvest_grade_vocabulary.py` fails if the two drift.
"""

from __future__ import annotations

# The free-text escape. Selecting it reveals a text box; the stored value is what the operator
# types, never this sentinel.
OTHER_GRADE = "__other__"
OTHER_GRADE_LABEL = "Other — as stated on the packing record"

# Grade families. Every string below is a published grade name for that commodity class.
GRADE_FAMILIES: dict[str, tuple[str, ...]] = {
    "apple": (
        "U.S. Extra Fancy",
        "U.S. Fancy",
        "U.S. No. 1",
        "U.S. Utility",
        # State marks. Washington packs to its own and a WA reviewer reads them as the grade.
        "WA Extra Fancy",
        "WA Fancy",
        "Processing",
    ),
    "pear": ("U.S. No. 1", "U.S. Combination", "U.S. No. 2", "Processing"),
    "citrus": ("U.S. Fancy", "U.S. No. 1", "U.S. Combination", "U.S. No. 2", "Juice"),
    "stone_fruit": ("U.S. Extra No. 1", "U.S. No. 1", "U.S. Combination", "U.S. No. 2", "Processing"),
    "berry": ("U.S. No. 1", "U.S. Combination", "U.S. No. 2", "Processing"),
    "table_grape": (
        "U.S. Extra Fancy Table",
        "U.S. Fancy Table",
        "U.S. No. 1 Table",
        "U.S. No. 1 Institutional",
        "Juice / Processing",
    ),
    # Roots and bulbs — carrots, onions, potatoes. The class Calapooia Bend actually grows.
    "root_bulb": ("U.S. Extra No. 1", "U.S. No. 1", "U.S. Commercial", "U.S. No. 2", "Processing"),
    "leafy": ("U.S. Fancy", "U.S. Extra No. 1", "U.S. No. 1", "U.S. Commercial", "Processing"),
    "fruiting_vegetable": ("U.S. No. 1", "U.S. Combination", "U.S. No. 2", "U.S. No. 3", "Processing"),
    "tree_nut": (
        "U.S. Fancy",
        "U.S. Extra No. 1",
        "U.S. No. 1",
        "U.S. Select Sheller Run",
        "U.S. Standard Sheller Run",
        "Manufacturing",
    ),
    "grain": (
        "U.S. No. 1",
        "U.S. No. 2",
        "U.S. No. 3",
        "U.S. No. 4",
        "U.S. No. 5",
        "U.S. Sample grade",
    ),
    "olive": ("U.S. Grade A (Fancy)", "U.S. Grade B (Choice)", "U.S. Grade C (Standard)", "Oil stock"),
    "date": ("U.S. Grade A", "U.S. Grade B", "U.S. Grade C"),
    "fig": ("U.S. No. 1", "U.S. No. 2", "Processing"),
    # Deliberately EMPTY. A crop with no USDA grade standard gets the free-text escape and
    # nothing else — see the module docstring.
    "none": (),
}

# Crop slug → family. Every active `CropType` slug must appear here; the guard test fails on a
# crop that is neither mapped nor explicitly declared as having no standard, so adding a crop
# to the catalogue forces a decision instead of silently inheriting a wrong list.
CROP_GRADE_FAMILY: dict[str, str] = {
    # tree fruit
    "apples": "apple",
    "pears": "pear",
    "citrus_oranges": "citrus",
    "stone_fruit": "stone_fruit",
    "grapes": "table_grape",
    "olives": "olive",
    "dates": "date",
    "figs": "fig",
    # No USDA grade standard exists for these, so none is offered.
    "avocados": "none",
    # `CROP_CUSTOMIZATIONS` carries a singular alias for this one; both must map, or the
    # every-crop-is-mapped guard is the only thing that would ever notice.
    "avocado": "none",
    "pomegranates": "none",
    "hops": "none",
    "cotton": "none",
    "hay_alfalfa": "none",
    # berries
    "blueberries": "berry",
    "strawberries": "berry",
    # tree nuts
    "almonds": "tree_nut",
    "walnuts": "tree_nut",
    "pecans": "tree_nut",
    "pistachios": "tree_nut",
    "hazelnuts": "tree_nut",
    # vegetables
    "carrots": "root_bulb",
    "onions": "root_bulb",
    "potatoes": "root_bulb",
    "spinach": "leafy",
    "lettuce": "leafy",
    "tomatoes": "fruiting_vegetable",
    # A mixed-vegetable production covers several commodity classes at once, so no single
    # family is right for it — the operator states what the packing record says.
    "mixed_vegetables": "none",
    # grains, oilseeds, legumes — all graded on the federal grain standards.
    "corn_field": "grain",
    "wheat": "grain",
    "rice": "grain",
    "soybeans": "grain",
    "sunflowers": "grain",
    "peanuts": "grain",
}

# Values written before this change. Kept in the choice tuple so an old row still renders its
# label instead of a bare slug in the packet and the admin.
LEGACY_GRADE_LABELS: dict[str, str] = {
    # ProductionEvent.harvest_quality_grade
    "export_quality": "Export Quality (legacy)",
    "grade_a": "Grade A (legacy)",
    "grade_b": "Grade B (legacy)",
    "grade_c": "Grade C (legacy)",
    "domestic": "Domestic Market (legacy)",
    "processing": "Processing (legacy)",
    # History.quality_grade
    "premium": "Premium Grade (legacy)",
    "standard": "Standard (legacy)",
}


def grades_for_crop(crop_slug: str | None) -> tuple[str, ...]:
    """The grade options for one crop. Empty when the commodity has no USDA standard."""
    family = CROP_GRADE_FAMILY.get((crop_slug or "").strip().lower())
    return GRADE_FAMILIES.get(family or "none", ())


def all_grades() -> tuple[str, ...]:
    """Every grade in the catalogue, in family order, de-duplicated."""
    seen: list[str] = []
    for grades in GRADE_FAMILIES.values():
        for grade in grades:
            if grade not in seen:
                seen.append(grade)
    return tuple(seen)


# ⛔ There is deliberately NO `grade_choices()` for the model fields, and no `choices=` on
# either column.
#
# It existed for about an hour on 2026-08-21 and was wrong in both directions. Declaring the
# catalogue as `choices` makes DRF generate a ChoiceField on every serializer that exposes the
# column, so the free-text escape — the option the picker always offers, because private buyer
# grades and state marks are real — answered **400 "…is not a valid choice"**. The UI rendered
# a text box the API refused. And `get_..._display()` would then have printed a row written
# before the change as "Grade A (legacy)": the word "legacy" is a note to us, not something a
# certifier should read.
#
# So the catalogue is a SUGGESTION, which is what it always claimed to be. The forms offer it,
# the column stores what the operator confirmed, and the packet renders that through
# `_humanize_enum` — verbatim for a real grade, still de-slugged for an old `grade_a`.


#: The longest value the catalogue itself can produce. Free text is bounded by the column.
MAX_GRADE_LENGTH = 60
