from django.db import migrations


def deactivate_extra_storage(apps, schema_editor):
    AddOn = apps.get_model("subscriptions", "AddOn")
    updated = AddOn.objects.filter(slug="extra-storage").update(is_active=False)
    if updated:
        print(f"Deactivated {updated} extra-storage add-on(s)")


def reactivate_extra_storage(apps, schema_editor):
    AddOn = apps.get_model("subscriptions", "AddOn")
    AddOn.objects.filter(slug="extra-storage").update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0005_add_invoice_number_field"),
    ]

    operations = [
        migrations.RunPython(deactivate_extra_storage, reactivate_extra_storage),
    ]
