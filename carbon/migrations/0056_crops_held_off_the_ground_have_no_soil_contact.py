# Puts crops outside the tree categories whose edible part is held off the ground on the 90-day
# raw-manure floor of 7 CFR 205.203(c)(1)(iii).
#
# 0037 and 0055 set has_soil_contact=False by CATEGORY (tree_fruit, tree_nut). Every other crop
# kept the field default True, the 120-day floor of (c)(1)(ii). For blueberries that was false:
# on 2026-11-16, in a browser on a freshly seeded database, the soil form refused 90 days on
# blueberries with "the edible part touches the soil, so 7 CFR 205.203(c)(1)(ii) requires at
# least 120 days", and the inspector's dossier cited (c)(1)(ii) on every blueberry season. The
# category "berry" cannot decide it, because it also holds strawberries, which do lie on the soil.
#
# The crop seeder now states the flag on these entries; this brings existing rows into line.
# Only a True is moved, and only on the slugs named here. Under the floor reading a False flag
# never blocks a 120-day record; it only stops refusing 90.
#
# Left at 120 on purpose: soybeans (the lowest pods can rest on the soil), tomatoes (staked or
# sprawling), hay (dried on the ground in windrows), strawberries, peanuts, roots and greens.
#
# Reverse is a no-op: the earlier True values were the field default, not a decision.

from django.db import migrations

HELD_OFF_THE_GROUND_SLUGS = (
    "blueberries",
    "hops",
    "corn_field",
    "wheat",
    "rice",
    "sunflowers",
    "cotton",
)


def crops_held_off_the_ground_have_no_soil_contact(apps, schema_editor):
    CropType = apps.get_model("carbon", "CropType")
    CropType.objects.filter(slug__in=HELD_OFF_THE_GROUND_SLUGS, has_soil_contact=True).update(has_soil_contact=False)


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0055_tree_crops_have_no_soil_contact"),
    ]

    operations = [
        migrations.RunPython(crops_held_off_the_ground_have_no_soil_contact, migrations.RunPython.noop),
    ]
