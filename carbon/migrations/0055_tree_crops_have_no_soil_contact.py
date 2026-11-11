# Re-applies 0037's data step to crop rows created after it ran.
#
# 0037 set has_soil_contact=False for the tree_fruit and tree_nut rows that existed at the
# time. The crop seeder never set the flag, so every crop it created later (and every crop on
# a freshly seeded database) kept the field default True: the 120-day soil-contact floor of
# 7 CFR 205.203(c)(1)(ii). On those databases the soil form refused the 90 days the rule
# allows apples and walnuts. The seeder now sets the flag from the category; this brings the
# rows that already exist into line. No-op where 0037's update already holds.
#
# Nothing records whether a True on a tree crop is the stale default or a decision. One decision
# is documented: the Solana Verde demo seeder (history/management/commands/_solana_verde_base.py)
# creates "avocados" with has_soil_contact=True because the fruit is collected from the ground,
# which puts it on the 120-day floor. That row is left as it is (review of back #371). Under the
# floor reading a False flag never blocks a 120-day record anyway; it only stops refusing 90.
#
# Reverse is a no-op: the earlier True values on the rows changed were the default.

from django.db import migrations

TREE_CATEGORIES = ("tree_fruit", "tree_nut")
DOCUMENTED_SOIL_CONTACT_SLUGS = ("avocados",)


def tree_crops_have_no_soil_contact(apps, schema_editor):
    CropType = apps.get_model("carbon", "CropType")
    (
        CropType.objects.filter(category__in=TREE_CATEGORIES, has_soil_contact=True)
        .exclude(slug__in=DOCUMENTED_SOIL_CONTACT_SLUGS)
        .update(has_soil_contact=False)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0054_retire_optimized_carbon_calculation"),
    ]

    operations = [
        migrations.RunPython(tree_crops_have_no_soil_contact, migrations.RunPython.noop),
    ]
