"""Give hydrogen peroxide its two § 205.601 rows on deployed databases.

The seed listed hydrogen peroxide twice under § 205.601, (a) algicide/disinfectant/sanitizer and (i)
plant disease control, with the same name. Rows are unique per (normalized name, section) and the
seeder upserts on that key, so the (i) entry overwrote the (a) row on every run: a seeded database
holds ONE row, last written as (i), and every citation printed § 205.601(i) (production seed,
2026-11-02: 105 updated over 104 rows).

Production receives catalogue rows only through migrations (start.sh runs `migrate`, never a
seeder), so the seeder fix alone would never reach it (see 0038).

Order matters. Chemical records, plan approvals and material entries point at the shared row by pk
and have printed (i). So that row is renamed IN PLACE to the (i) listing's qualified name first, and
those records keep the citation they printed; the (a) sanitizer row is then created new. Upserting
the bare name first would rewrite the shared row as (a) and silently move every existing link to the
sanitizer citation.

Idempotent, and a no-op on a fresh database, which gets both rows from the seeder. Frozen here
rather than imported from the seeder: a migration must replay identically forever.
"""

import re

from django.db import migrations

SECTION = "205.601"
BARE = "Hydrogen peroxide"
QUALIFIED = "Hydrogen peroxide (disease control)"
DISEASE_NOTE = "Same as § 205.601(a) sanitizer use; allowed for plant disease control."


def _normalize(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def split_listings(apps, schema_editor):
    Substance = apps.get_model("certifications", "NationalListSubstance")

    # Only a database seeded while the two listings shared the bare name has work to do: one
    # (205.601, "hydrogen peroxide") row written as (i), and no qualified row yet. A fresh database
    # has neither and gets both rows from the seeder; a database already split is left alone.
    shared = Substance.objects.filter(cfr_section=SECTION, substance_name_normalized=_normalize(BARE), subsection="i")
    already_split = Substance.objects.filter(cfr_section=SECTION, substance_name_normalized=_normalize(QUALIFIED))
    if not shared.exists() or already_split.exists():
        return

    shared.update(
        substance_name=QUALIFIED,
        substance_name_normalized=_normalize(QUALIFIED),
        category="disease_control",
        restriction_notes=DISEASE_NOTE,
        annotation_kind="condition_of_use",
    )
    Substance.objects.create(
        substance_name=BARE,
        substance_name_normalized=_normalize(BARE),
        cfr_section=SECTION,
        subsection="a",
        category="sanitizer",
        status="allowed",
        restriction_notes=None,
        annotation_kind="none",
    )


class Migration(migrations.Migration):
    dependencies = [("certifications", "0063_brand_owner_register")]

    # Reverse is a no-op: deleting or merging catalogue rows would cascade through every record that
    # points at one.
    operations = [migrations.RunPython(split_listings, migrations.RunPython.noop)]
