"""Retire `SoilManagementEvent.carbon_sequestration_potential` from the model, step 2 of 3.

Step 1 (back #483) stopped every reader and writer (history/retired_columns.py). In production on
2026-11-18 the census `before-soil-retire` (ops/census/20261118T163117Z-before-soil-retire-
e6d4e1c5e317.json) counted 0 rows holding a value, and `clear_retired_soil_columns --apply`
changed 0 rows.

The column cannot leave the TABLE yet: `migrate` runs when the new container boots, while the
previous containers still serve, and their model still names the column in every soil event
INSERT and UPDATE. So this migration refuses to run if any row holds a value (the deploy then
fails and the old containers keep serving), then removes the field from the model state only.
The column is already nullable and has no index or default, so the database side has nothing to
do. Step 3, a later migration once this is live, drops the column from the table.

Reversing it puts the field back in the model; the table never changed.
"""

from django.db import migrations

#: Same list as history/retired_columns.py, frozen here: a migration must not change when that
#: module does.
RETIRED = ("carbon_sequestration_potential",)


def refuse_if_a_value_is_held(apps, schema_editor):
    SoilManagementEvent = apps.get_model("history", "SoilManagementEvent")
    held = {}
    for column in RETIRED:
        count = SoilManagementEvent.objects.filter(**{f"{column}__isnull": False}).count()
        if count:
            held[column] = count
    if held:
        raise RuntimeError(
            f"history 0266: rows still hold a value in retired columns {held}. Run "
            "`clear_retired_soil_columns --apply` from the #483 release first; nothing was changed."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0265_production_permissions_take_over_history"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_value_is_held, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="soilmanagementevent", name="carbon_sequestration_potential"),
            ],
            database_operations=[],
        ),
    ]
