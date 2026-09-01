"""Distinguish a CHOSEN disclosure level from an INHERITED one.

Migration 0013 introduced `location_disclosure_level` and wrote `exact` onto every parcel that
already existed, because those parcels were already publishing field boundaries and narrowing
that silently would have changed what farms had agreed to show. That was right.

What was missed is that the setting was never surfaced in the producer app. So those farms have
been publishing a boundary under a value they were never shown and cannot reach, while the
marketing site describes the disclosure level as their control. This migration adds the flag
that lets the product tell the two populations apart and ask only the farms that were never
asked.

The backfill marks `approximate` and `hidden` as settled. Neither publishes a boundary, so
there is nothing to warn about and a prompt would be noise; if such a farm later wants `exact`,
that is an ordinary opt-in through the same control. Only `exact` is left unsettled, which is
exactly the population the prompt is for.

Reverse leaves the flag alone before dropping the column — a rollback should not be able to
re-arm a prompt for someone who has already answered it.
"""

from django.db import migrations, models


def settle_non_publishing_levels(apps, schema_editor):
    Parcel = apps.get_model("product", "Parcel")
    Parcel.objects.filter(location_disclosure_level__in=("approximate", "hidden")).update(
        location_disclosure_choice_made=True
    )


def noop(apps, schema_editor):
    """Deliberately empty. See the module docstring."""


class Migration(migrations.Migration):

    dependencies = [
        ("product", "0025_alter_parcel_area"),
    ]

    operations = [
        migrations.AddField(
            model_name="parcel",
            name="location_disclosure_choice_made",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True once someone at the operation has explicitly confirmed or changed "
                    "location_disclosure_level. False means the value was inherited, not chosen."
                ),
            ),
        ),
        migrations.RunPython(settle_non_publishing_levels, noop),
    ]
