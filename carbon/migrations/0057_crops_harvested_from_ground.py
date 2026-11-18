# Marks the seeded tree nuts that are shaken to the orchard floor and swept up at harvest.
#
# Their floor stays 90 days (7 CFR 205.203(c)(1)(iii)): the kernel does not touch the soil. The shell does,
# and certifiers can read that as soil contact under (c)(1)(ii), 120 days. Nothing found from CCOF, OTCO or
# WSDA settles it (2026-11-18), so the dossier names both readings when a raw manure interval under 120 days
# meets one of these crops, for the certifier to confirm, and no record is refused.
#
# Pistachios are left out: they are shaken onto catch frames, not the ground. Reverse is a no-op beyond the
# field itself.

from django.db import migrations, models

HARVESTED_FROM_GROUND_SLUGS = ("walnuts", "almonds", "pecans", "hazelnuts")


def mark_crops_harvested_from_ground(apps, schema_editor):
    CropType = apps.get_model("carbon", "CropType")
    CropType.objects.filter(slug__in=HARVESTED_FROM_GROUND_SLUGS).update(harvested_from_ground=True)


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0056_crops_held_off_the_ground_have_no_soil_contact"),
    ]

    operations = [
        migrations.AddField(
            model_name="croptype",
            name="harvested_from_ground",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Whether the crop is gathered from the ground at harvest (nuts shaken to the orchard floor and "
                    "swept). A raw manure interval under 120 days on such a crop is printed for the certifier to "
                    "confirm."
                ),
            ),
        ),
        migrations.RunPython(mark_crops_harvested_from_ground, migrations.RunPython.noop),
    ]
