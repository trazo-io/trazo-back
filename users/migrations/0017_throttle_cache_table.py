"""Create the Postgres table behind the `throttle` cache (OV-SEC-C06).

The security throttles (sign-in, sign-up, password reset, email verification, invitation accept,
company-code check) count in `CACHES["throttle"]`, a DatabaseCache, because production keeps
`default` as DummyCache on purpose (see the CACHES note in backend/settings/base.py). Django
creates DatabaseCache tables with `createcachetable`, not with migrations, so this migration runs
it: a deploy then needs no manual step, and every test database gets the table too.

`createcachetable` is idempotent (it skips a table that exists) and creates the tables of every
DatabaseCache alias in settings. If the table is ever renamed, add a migration like this one.
"""

from django.core.management import call_command
from django.db import migrations


def create_throttle_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0016_email_change_request_and_credentials_changed_at"),
    ]

    operations = [
        migrations.RunPython(create_throttle_cache_table, migrations.RunPython.noop),
    ]
