"""Rename the "Extra Establishment" add-on's DISPLAY name to "Extra Farm".

UI naming rule: an Establishment is a "Farm" everywhere a farmer reads it. The add-on card on
the subscription page printed the raw AddOn.name, so it was the one purchasable thing in the
app still speaking model-ese. The slug (`extra-establishment`) is an identifier referenced by
code and Stripe metadata and does NOT change.
"""

from django.db import migrations


def rename_to_farm(apps, schema_editor):
    AddOn = apps.get_model("subscriptions", "AddOn")
    AddOn.objects.filter(slug="extra-establishment").update(name="Extra Farm")


def rename_back(apps, schema_editor):
    AddOn = apps.get_model("subscriptions", "AddOn")
    AddOn.objects.filter(slug="extra-establishment").update(name="Extra Establishment")


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0012_retire_enterprise_self_serve"),
    ]

    operations = [
        migrations.RunPython(rename_to_farm, rename_back),
    ]
