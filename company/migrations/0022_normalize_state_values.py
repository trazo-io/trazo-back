"""Canonicalize Company/Establishment.state to 2-letter US codes.

Every regional lookup downstream (irrigation depth, precipitation, USDA
regional factors, the CA-only compliance surfaces) keys on the 2-letter code,
but `state` is a free-text CharField and a large share of existing rows hold
the full name "California". Those rows only ever reached California factors via
the `len(state) != 2 -> "CA"` fallback in the carbon calculator, which is being
removed — so they must be canonicalized first or they would silently switch to
national defaults.

Unresolvable values are deliberately LEFT ALONE rather than blanked: some are
genuinely not US states (e.g. "Salto", a Uruguayan department), and blanking
destroys information a human could still recover. `manage.py audit_state_values`
lists them.
"""

from django.db import migrations

from common.us_states import normalize_state


def normalize_states(apps, schema_editor):
    for model_name in ("Company", "Establishment"):
        model = apps.get_model("company", model_name)
        updates = []
        for row in model.objects.exclude(state="").only("id", "state"):
            resolved = normalize_state(row.state)
            if resolved and resolved != row.state:
                row.state = resolved
                updates.append(row)
        if updates:
            model.objects.bulk_update(updates, ["state"], batch_size=500)


def noop_reverse(apps, schema_editor):
    """Irreversible by design — the original free-text spelling is not recoverable."""


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0021_establishment_show_full_performer_names"),
    ]

    operations = [
        migrations.RunPython(normalize_states, noop_reverse),
    ]
