"""Phase two: actually DROP the transparency_score column.

Phase one was history/0237, which removed the field from Django's STATE and dropped the column's
NOT NULL constraint while leaving the column itself in place. Its docstring explains why the two
cannot ship together: `start.sh` runs `migrate` inside the NEW container before gunicorn boots
and DO App Platform keeps the OLD container serving until the new one passes its health check, so
a single-deploy drop leaves a window in which the old container's model still declares a column
the database no longer has, and Django's default SELECT names every declared field.

THE PRECONDITION FOR THIS MIGRATION, AND THE EVIDENCE IT WAS MET
----------------------------------------------------------------
No running container may declare the field. Phase one shipped in PR #76 and reached production
before this was written:

    deployment b5121e93  ACTIVE 13/13  2026-10-01 12:14:48 UTC
    deploy log           "Applying history.0237_remove_history_transparency_score... OK"
                         at 2026-10-01T12:17:26Z

So the only code serving traffic is the version whose `History` model has no
`transparency_score` field at all. Dropping the column now cannot break a SELECT, because nothing
names it.

NEVER squash 0237 and 0238 together, and never reorder them into one deploy. The pair looks like
one redundant migration and is not: the gap between them IS the mechanism.

The state is already correct, so this is database_operations only. A `RemoveField` here would
raise, because 0237 removed the field from state two migrations ago.

Reverse adds the column back exactly as 0237 leaves it: `double precision`, NULL-able, no
database default (verified against information_schema, not assumed). Reversing this and then
0237 therefore works in sequence, with 0237's own reverse filling the NULLs before restoring NOT
NULL. Reversing does NOT restore the values: every score in that column was a number this
product no longer computes.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0237_remove_history_transparency_score"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Nothing to do: 0237 already took the field out of Django's state.
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "history_history" DROP COLUMN "transparency_score"',
                    reverse_sql=(
                        'ALTER TABLE "history_history" '
                        'ADD COLUMN "transparency_score" double precision NULL'
                    ),
                ),
            ],
        ),
    ]
