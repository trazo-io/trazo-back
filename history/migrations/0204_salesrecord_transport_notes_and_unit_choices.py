"""Align the sale unit vocabulary with the harvest one, and give "Other" its notes.

`SalesRecord.quantity_unit` was the only unit column in the schema with no `choices` —
`History.production_unit` and `History.quantity_sold_unit` both had them — so the editor drifted
to its own list and offered `tonnes` where the harvest form offers `tons`. The audit export only
prints the mass-balance Balance line and the "sold exceeds harvest" review flag when
`harvest_unit == sold_unit`, so the same weight spelled two ways silently removed
§ 205.103(b)(2) reconciliation from the certifier packet.

The sales form was the only writer that could produce `tonnes`, so the forward mapping is exact
rather than a guess. (The column had no `choices`, so the API would have accepted any string;
this normalizes the one value the product could actually create and leaves anything else alone
rather than guessing at it.) The reverse is a no-op on purpose: after the merge there is no way
to tell a row entered as `tonnes` from one entered as `tons`, and inventing a split would be the
migration editing the operator's record.
"""

from django.db import migrations, models


def normalize_tonnes_to_tons(apps, schema_editor):
    SalesRecord = apps.get_model("history", "SalesRecord")
    SalesRecord.objects.filter(quantity_unit="tonnes").update(quantity_unit="tons")


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0203_salesrecord_prior_products_transported_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_tonnes_to_tons, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="salesrecord",
            name="quantity_unit",
            field=models.CharField(
                choices=[
                    ("kg", "Kilograms"),
                    ("lb", "Pounds"),
                    ("boxes", "Boxes"),
                    ("crates", "Crates"),
                    ("tons", "Tons"),
                    ("bushels", "Bushels"),
                    ("units", "Units"),
                ],
                default="kg",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="salesrecord",
            name="transport_notes",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "What the 'Other' cleaning method or 'Other' inspection finding actually was. "
                    "Required whenever either is selected; blank otherwise means nothing to add."
                ),
                max_length=300,
            ),
        ),
    ]
