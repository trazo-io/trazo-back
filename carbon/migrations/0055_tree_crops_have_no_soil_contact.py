# Re-applies 0037's data step to crop rows created after it ran.
#
# 0037 set has_soil_contact=False for the tree_fruit and tree_nut rows that existed at the
# time. The crop seeder never set the flag, so every crop it created later (and every crop on
# a freshly seeded database) kept the field default True: the 120-day soil-contact floor of
# 7 CFR 205.203(c)(1)(ii). On those databases the soil form refused the 90 days the rule
# allows apples and walnuts. The seeder now sets the flag from the category; this brings the
# rows that already exist into line. No-op where 0037's update already holds.
#
# Reverse is a no-op: the earlier True values were the default, not a recorded decision.

from django.db import migrations

TREE_CATEGORIES = ("tree_fruit", "tree_nut")


def tree_crops_have_no_soil_contact(apps, schema_editor):
    CropType = apps.get_model("carbon", "CropType")
    CropType.objects.filter(category__in=TREE_CATEGORIES, has_soil_contact=True).update(has_soil_contact=False)


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0054_retire_optimized_carbon_calculation"),
    ]

    operations = [
        migrations.RunPython(tree_crops_have_no_soil_contact, migrations.RunPython.noop),
    ]
