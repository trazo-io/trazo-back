"""Remove History.transparency_score from Django's STATE, and let the column accept NULL.

The column itself survives this deploy. The real DROP COLUMN is a follow-up, and the two cannot
ship together. This docstring is the reason why.

WHAT CAME OUT
-------------
The score was retired as a CONCEPT on 2026-09-08 (.claude/rules/transparency-first.md): the
producer dashboard shows counts, and no surface carries a total, percentage or grade. back #70
removed the readers that served it (two serializers and a `.only()` list) and stopped
`update_trust_metrics()` rewriting it on every event create, edit and delete. THIS change removes
the remaining Python references: the model field, `HistoryAdmin` (list_display, readonly_fields
and a fieldset) and `auditlog_registry`'s exclude_fields.

NEVER DROP THIS COLUMN IN THE SAME DEPLOY THAT REMOVES THE FIELD
----------------------------------------------------------------
`start.sh` runs `manage.py migrate` inside the NEW container, before gunicorn boots, and DO App
Platform keeps the OLD container serving until the new one passes its health check. So between
the migration finishing and traffic switching there is a window, roughly a minute, in which:

    old container  = model DECLARES transparency_score
    database       = whatever this migration just did

Django's default SELECT names every declared field. If the column were gone, every read of
History on the old container would raise `ProgrammingError: column
history_history.transparency_score does not exist` for that window. Not just the Django admin:
the consumer QR page, the producer season list and the audit export all read seasons.

Hence the split, which is the standard two-phase pattern:

    0237 (this one)   state only, plus DROP NOT NULL. The column stays and keeps its values.
                      Old container: field declared, column present, reads and writes fine.
                      New container: field absent, column ignored.
    the follow-up     ALTER TABLE ... DROP COLUMN, in a LATER deploy, once no running container
                      declares the field. Must not merge until this one is ACTIVE in production.

WHY DROP NOT NULL IS NOT OPTIONAL HERE
--------------------------------------
Removing a field from state alone is NOT a safe half-step, and this is the trap worth
remembering. The column was created from `FloatField(default=0)`, which in Postgres is NOT NULL
with no database-level default: Django supplied the 0 in Python. Take the field out of state and
Django stops naming the column in INSERTs, so every `History` row created afterwards fails with

    NotNullViolation: null value in column "transparency_score" of relation "history_history"

The backend suite produced 762 of those before this line was added. A state-only removal would
have shipped a migration that broke EVERY season creation in production, which is worse than the
rollover window it was written to avoid.

PROVENANCE
----------
A review on PR #76 caught the first version of this migration: its docstring credited #70 with
removing the admin and auditlog readers and concluded the deploy order was therefore safe. #70
touched neither file; this change does. The claim was false and the conclusion it supported was
false, which is how a rollover window came to be written down as a safety argument.

carbon/0040 deletes ConsumerTrustMetric's TABLE in one step, deliberately and safely: nothing in
any request path ever read or wrote that model (its only references were an unused import and a
management command), so there is no old-container query to break.
"""

from django.db import migrations

# Reverse order matters: the column holds NULLs for every row written while the field was absent,
# so they have to be filled before NOT NULL can come back. 0 is what the field's own default was.
_RESTORE_NOT_NULL = """
UPDATE "history_history" SET "transparency_score" = 0 WHERE "transparency_score" IS NULL;
ALTER TABLE "history_history" ALTER COLUMN "transparency_score" SET NOT NULL;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0236_alter_chemicalevent_ffm_code"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Django's model state loses the field, so no query names the column again.
            state_operations=[
                migrations.RemoveField(
                    model_name="history",
                    name="transparency_score",
                ),
            ],
            # The column is NOT dropped here. It only stops being mandatory, so inserts that no
            # longer mention it succeed while the old container still reads and writes it.
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "history_history" ALTER COLUMN "transparency_score" DROP NOT NULL',
                    reverse_sql=_RESTORE_NOT_NULL,
                ),
            ],
        ),
    ]
