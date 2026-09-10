"""Correct the § 205.602 catalogue rows to the eCFR text, with their paragraph letters.

The rows carried paraphrased notes ("Allowed only as foliar spray for calcium uptake disorders.")
and no subsection, so a packet could cite calcium chloride only as "§ 205.602" and quote a
sentence the rule does not contain. A WSDA desk read (2026-09-10) put the note in front of the
reviewer, beside a Honeycrisp block's calcium sprays, which made the wording matter.

UPDATE ONLY — a row that does not exist is not created. Migration 0038 created catalogue rows and a
fresh database then reported the National List as seeded while holding only handling sanitizers;
creating the ten § 205.602 rows here would repeat that with the prohibited list alone.
`seed_national_list` carries the same text for a database it seeds.

`annotation_kind` stays what it was: the three annotated rows remain "condition_of_use", which is
the field every reader branches on (`is_conditionally_permitted`), never the note's wording.
Text verified against the eCFR, Title 7 part 205 (issue of 2026-09-04), fetched 2026-09-10.
Frozen here rather than imported from the seeder — a migration must replay identically forever.
"""

import re

from django.db import migrations

ROWS = [
    ("a", "Ash from manure burning", None),
    ("b", "Arsenic", None),
    (
        "c",
        "Calcium chloride (brine process)",
        "Prohibited for use except as a foliar spray to treat a physiological disorder associated with calcium uptake.",
    ),
    ("d", "Lead salts", None),
    (
        "e",
        "Potassium chloride",
        "Unless derived from a mined source and applied in a manner that minimizes chloride accumulation in the soil.",
    ),
    ("f", "Rotenone", None),
    ("g", "Sodium fluoaluminate (mined)", None),
    (
        "h",
        "Sodium nitrate",
        "Unless use is restricted to no more than 20% of the crop's total nitrogen requirement; use in spirulina "
        "production is unrestricted until October 21, 2005.",
    ),
    ("i", "Strychnine", None),
    ("j", "Tobacco dust (nicotine sulfate)", None),
]


def _normalize(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def correct(apps, schema_editor):
    Substance = apps.get_model("certifications", "NationalListSubstance")
    for subsection, name, notes in ROWS:
        Substance.objects.filter(cfr_section="205.602", substance_name_normalized=_normalize(name)).update(
            subsection=subsection,
            restriction_notes=notes,
            annotation_kind="condition_of_use" if notes else "none",
        )


class Migration(migrations.Migration):
    dependencies = [("certifications", "0038_national_list_205_605_sanitizers")]

    # Reverse is a no-op: the old wording was a paraphrase, not a state worth restoring.
    operations = [migrations.RunPython(correct, migrations.RunPython.noop)]
