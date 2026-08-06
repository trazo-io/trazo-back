"""
Backfill the 26 published events carrying truncated one-letter subtype codes.

WHY: history/tests/test_event_subtype_validation.py documents that ProductionEvent.save()
and ChemicalEvent.save() do not validate `choices` (only full_clean() does), so a raw ORM
write with an invalid `type` succeeds silently. All 26 affected rows sit on the 5
"GreenHarvest ... QR Test" demo productions (histories 125-129) used to showcase the
consumer QR page — none are real pilot-farmer data, and none of Trazo's current
`carbon/management/commands/seed_*.py` scripts write a single-letter code (verified via
grep), so whatever ad-hoc process created these rows is not part of the live seed pipeline.
That means there is no recurring source to fix — this migration closes the existing gap.

Every mapping below was confirmed per-row against `extra_data.event_template_name` /
`commercial_name`, not guessed from the letter alone:
  - ProductionEvent "H"  -> "HA" (Harvesting) — the only H-prefixed choice; all 10 rows'
    templates are "Harvest", "Combine Harvest Operation" or "Harvest Equipment Operation".
  - ProductionEvent "P"  -> "PL" (Planting) — all 9 rows' templates are "Planting",
    "No-Till Planting (Conservation)", "No-Till Soybean Planting", "Planting/Seeding
    Equipment" or "Precision Planting Equipment"; none reference pruning, pollination or
    post-harvest processing (the other 3 P*-prefixed choices).
  - ChemicalEvent "F"    -> "FE" (Fertilizer) — the only F-prefixed choice; all 6 rows'
    templates are "Spring Fertilization", "Fertilizer Application" or "Sprayer Operations
    (Fertilizer & Pesticide Application)".
  - ChemicalEvent "P"    -> "HE" (Herbicide) — genuinely ambiguous: this single row
    (id=125, history 126) is a tank-mix product, `commercial_name` "Test Sprayer Operations
    (Herbicide & Fungicide)", matching neither HE nor FU by truncation and naming Herbicide
    first. No `chemical_subtype` or `target_pest_disease` on the row to disambiguate
    further. Herbicide is the closer read; flagged here rather than silently guessed.
"""

from django.db import migrations

PRODUCTION_EVENT_MAP = {"H": "HA", "P": "PL"}
CHEMICAL_EVENT_MAP = {"F": "FE", "P": "HE"}


def backfill(apps, schema_editor):
    ProductionEvent = apps.get_model("history", "ProductionEvent")
    ChemicalEvent = apps.get_model("history", "ChemicalEvent")

    for bad, good in PRODUCTION_EVENT_MAP.items():
        ProductionEvent.objects.filter(type=bad).update(type=good)

    for bad, good in CHEMICAL_EVENT_MAP.items():
        ChemicalEvent.objects.filter(type=bad).update(type=good)


def reverse(apps, schema_editor):
    # Not reversible: the original truncated codes were data corruption, not a state worth
    # restoring. A reverse run is a no-op rather than re-truncating good data.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0188_pestmanagementevent_observation_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
