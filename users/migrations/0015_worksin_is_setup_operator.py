from django.db import migrations, models

# Inlined, not imported: a migration must not depend on app code that can change later. Same
# value as `subscriptions.pilot_operator.SETUP_SUFFIX`.
SETUP_SUFFIX = "(Trazo setup)"


def flag_suffixed_operators(apps, schema_editor):
    """Flag the memberships of accounts that carry the setup suffix.

    Only those: `create_operator_account` applies the suffix to every NEW operator account, so it
    proves the account is one. An existing account attached by `add_pilot_operator --email` or
    `provision_pilot` kept its own name and cannot be told apart from a grower here. Those are
    flagged by re-running `add_pilot_operator --company-id <id> --email <email> --commit`, which
    sets the flag on an existing membership too.
    """
    WorksIn = apps.get_model("users", "WorksIn")
    WorksIn.objects.filter(user__last_name__endswith=SETUP_SUFFIX).update(is_setup_operator=True)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0014_user_terms_acceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="worksin",
            name="is_setup_operator",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(flag_suffixed_operators, migrations.RunPython.noop),
    ]
