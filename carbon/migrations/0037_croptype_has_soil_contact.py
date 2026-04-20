# Sprint 1.2 — NOP 7 CFR 205.203(c)(1) Manure Harvest Interval Flag
#
# Adds has_soil_contact to CropType. Seeds the flag for the existing 22 Trazo crops:
#   - tree_fruit, tree_nut  -> has_soil_contact=False (90-day manure interval)
#   - everything else       -> has_soil_contact=True  (120-day manure interval)
#
# Default is True (conservative — enforces the stricter 120-day window when data is unknown).

from django.db import migrations, models


TREE_CATEGORIES = ("tree_fruit", "tree_nut")


def seed_soil_contact(apps, schema_editor):
    CropType = apps.get_model("carbon", "CropType")
    CropType.objects.filter(category__in=TREE_CATEGORIES).update(has_soil_contact=False)
    # All other categories keep the default True (set in field default).


def reverse_seed_soil_contact(apps, schema_editor):
    """Field drop handles reversal; nothing explicit to undo here."""


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0036_add_berry_forage_crop_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="croptype",
            name="has_soil_contact",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Whether the edible portion of this crop contacts the soil. "
                    "Determines the raw-manure harvest interval per NOP 7 CFR 205.203(c)(1) "
                    "(True = 120 days, False = 90 days). Conservative default is True."
                ),
            ),
        ),
        migrations.RunPython(seed_soil_contact, reverse_code=reverse_seed_soil_contact),
    ]
