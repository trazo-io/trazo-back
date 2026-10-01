"""Drop History.transparency_score, the stored 0-100 self-grade.

The score was retired as a CONCEPT on 2026-09-08 (.claude/rules/transparency-first.md):
the producer dashboard shows counts, and there is no total, percentage or grade on any
surface. back #70 removed every reader on 2026-09-30 (two serializers, a .only() list, the
Django admin, the auditlog exclude list) and stopped update_trust_metrics() rewriting it on
every event create, edit and delete. This is the storage.

Reversible in schema, not in data: reversing re-adds the column with its 0 default and the
stored grades do not come back. That is intentional. Every value in it was a self-assigned
number this product no longer computes, and recomputing it would mean restoring the
calculator method deleted in #70.

Deploy order matters and was respected: #70's deploy reached ACTIVE before this migration
ships, so no running container reads the column while it is being dropped.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0236_alter_chemicalevent_ffm_code"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="history",
            name="transparency_score",
        ),
    ]
