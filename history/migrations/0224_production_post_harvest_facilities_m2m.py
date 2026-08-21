"""One lot, MANY off-farm handlers (7 CFR 205.272 / Common OSP G6.1).

`History.post_harvest_facility` was a single ForeignKey, and a lot routinely has more than
one certified handler: Calapooia Bend ships each blueberry season's fresh grade to Organically
Grown Company and its process grade to Willamette Valley Fruit, on separate loads with separate
bills of lading. Five of that farm's nine shipped lots did exactly that, so the operator could
record at most half of what § 205.272 asks for — and the packet's "no handler certificate on
file" warning cleared the moment ONE handler was linked, which is worse than the warning itself:
the second handler's certificate silently stopped being asked for.

The existing links are carried across BEFORE the column is dropped. Ordering matters — the
auto-generated migration removed the column first, which would have thrown every link away.
"""

from django.db import migrations, models


def carry_links_forward(apps, schema_editor):
    History = apps.get_model("history", "History")
    for production in History.objects.exclude(post_harvest_facility__isnull=True).iterator():
        production.post_harvest_facilities.add(production.post_harvest_facility_id)


def carry_links_back(apps, schema_editor):
    """Reverse: keep the FIRST handler. A single column cannot hold more, and losing the
    others loudly (one survives, the rest do not) beats failing to reverse at all."""
    History = apps.get_model("history", "History")
    for production in History.objects.filter(post_harvest_facilities__isnull=False).distinct().iterator():
        first = production.post_harvest_facilities.order_by("id").first()
        if first is not None:
            production.post_harvest_facility_id = first.id
            production.save(update_fields=["post_harvest_facility"])


class Migration(migrations.Migration):

    dependencies = [
        ("certifications", "0028_nationallistsubstance_annotation_kind"),
        ("history", "0223_alter_businessevent_certification_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="history",
            name="post_harvest_facilities",
            field=models.ManyToManyField(
                blank=True, related_name="productions", to="certifications.postharvestfacility"
            ),
        ),
        migrations.RunPython(carry_links_forward, carry_links_back),
        migrations.RemoveField(
            model_name="history",
            name="post_harvest_facility",
        ),
    ]
