# Two migrations numbered 0256 merged to main a minute apart on 2026-11-11 (trazo-back #370 retires
# UserImpactSummary; #371 relabels the raw-manure interval choices). Both depend on 0255, so
# history had two leaf nodes and `migrate` refused to run ("Conflicting migrations detected"),
# failing the production deploy. They touch different models; this only joins the graph.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0256_manure_interval_choices_read_as_a_floor"),
        ("history", "0256_retire_impact_summary"),
    ]

    operations = []
