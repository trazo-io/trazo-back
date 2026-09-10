"""Seed the § 205.605(b) post-harvest sanitizers into the National List catalogue.

Production receives catalogue rows only through migrations (start.sh runs `migrate`, never a
seeder), so this is the one path by which these rows reach a deployed database. Idempotent:
`update_or_create` on the (normalized name, section) pair the unique constraint enforces, so a
database where `seed_national_list` already ran is left unchanged. Frozen here on purpose rather
than imported from the seeder — a migration must replay identically forever.
"""

import re

from django.db import migrations

# 7 CFR 205.605(b) — synthetic substances allowed in organic HANDLING, limited to the sanitizers a crop
# operation meets in post-harvest wash and rinse water and on food contact surfaces. Text verified
# against the eCFR versioner, Title 7 issue of 2026-09-04 (2026-09-10). § 205.601(a) lists sanitizers
# for crop PRODUCTION — equipment, irrigation, seed — so a flume sanitizer that could only be attached
# from § 205.601 printed on the packet under the wrong section (OTCO desk read, 2026-09-10).
# (b)(12) "Chlorine materials" is one entry with four named materials under one annotation.
CHLORINE_605 = (
    "disinfecting and sanitizing food contact surfaces, equipment and facilities may be used "
    "up to maximum labeled rates. Chlorine materials in water used in direct crop or food "
    "contact are permitted at levels approved by the FDA or EPA for such purpose, provided "
    "the use is followed by a rinse with potable water at or below the maximum residual "
    "disinfectant limit for the chlorine material under the Safe Drinking Water Act. Chlorine "
    "in water used as an ingredient in organic food handling must not exceed the maximum "
    "residual disinfectant limit for the chlorine material under the Safe Drinking Water Act."
)
ROWS = [
    (
        "b",
        "sanitizer",
        "Acidified sodium chlorite",
        "Secondary direct antimicrobial food treatment and indirect food contact surface sanitizing. Acidified with citric acid only.",
    ),
    ("b", "sanitizer", "Calcium hypochlorite", CHLORINE_605),
    ("b", "sanitizer", "Chlorine dioxide", CHLORINE_605),
    ("b", "sanitizer", "Hypochlorous acid (generated from electrolyzed water)", CHLORINE_605),
    ("b", "sanitizer", "Sodium hypochlorite", CHLORINE_605),
    ("b", "sanitizer", "Hydrogen peroxide", None),
    ("b", "sanitizer", "Ozone", None),
    (
        "b",
        "sanitizer",
        "Peracetic acid/Peroxyacetic acid",
        "For use in wash and/or rinse water according to FDA limitations. For use as a sanitizer on food contact surfaces.",
    ),
]


def _normalize(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def seed(apps, schema_editor):
    Substance = apps.get_model("certifications", "NationalListSubstance")
    for subsection, category, name, notes in ROWS:
        Substance.objects.update_or_create(
            substance_name_normalized=_normalize(name),
            cfr_section="205.605",
            defaults=dict(
                substance_name=name,
                subsection=subsection,
                category=category,
                status="allowed",
                restriction_notes=notes,
                annotation_kind="condition_of_use" if notes else "none",
            ),
        )


class Migration(migrations.Migration):
    dependencies = [("certifications", "0037_catalog_provenance_and_wsda_columns")]

    # Reverse is a no-op: deleting catalogue rows would cascade through every plan that attached one.
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
