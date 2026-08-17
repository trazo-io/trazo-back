"""Remove the trial keys migration 0009 left on the Compliance row.

THE BUG
-------
`0009_compliance_tier` wrote `trial_no_card_days: 14` and `trial_with_card_days: 14` into
`Plan.features` for `compliance-yearly`, and no later migration removed them. `create_plans`
already knows they must not be there — its `compliance_features` carries the comment "No trial
keys: Starter is the free path… the pricing page renders its trial line from these" — so the two
seeding paths disagreed, and which one a database took decided what the page said.

A `create_plans`-seeded database (a developer's, the one every screenshot came from) has no trial
keys and renders nothing. A migrate-only database — which is how production is built — kept them,
and the pricing page rendered "14-day free trial included" directly under the Select Plan button
of a $249/yr plan that has no trial and never had one. There is no code that would honour it:
`start_trial` assigns Starter with `trial_end=None`, and `expire_trials` has an empty
EXPIRABLE_TRIAL_PLAN_SLUGS and no-ops. It was a promise nothing in the system could keep, on the
one screen where a number is a commitment.

The frontend surface that read these keys is deleted in the same change. Both halves are needed:
deleting only the surface leaves a false value in the database for the next reader, and deleting
only the value leaves a live renderer waiting for one.

SCOPE: `compliance-yearly` ONLY
------------------------------
`pilot` is deliberately left alone even though it derives from Compliance. Both 0011 and
`create_plans` set its trial keys to an explicit `0`, so the two seeding paths already agree
there — stripping the keys would break that agreement and reintroduce exactly the class of bug
this migration exists to close. The retired ladder rows (basic/standard/corporate/enterprise)
keep theirs for the same reason: they are inactive, unsellable, and `create_plans` still
defines them.

NO SUBSCRIBERS ARE AFFECTED. Trazo has zero real users, and nothing reads these keys any more.
"""

from django.db import migrations

PHANTOM_TRIAL_KEYS = ("trial_no_card_days", "trial_with_card_days")

# Reverse restores exactly what 0009 wrote, so `migrate subscriptions 0014` round-trips to the
# state 0014 left behind rather than to a third, invented one.
REINSTATED_ON_REVERSE = {"trial_no_card_days": 14, "trial_with_card_days": 14}

AFFECTED_SLUGS = ("compliance-yearly",)


def _patch_features(Plan, slug, updates, remove=()):
    """Read-modify-write one plan's JSON features. A missing plan is a no-op, not an error: this
    must run on a fresh database seeded by `create_plans` (which already omits the keys) as well
    as on one built by migrations alone."""
    plan = Plan.objects.filter(slug=slug).first()
    if plan is None:
        return
    features = dict(plan.features or {})
    features.update(updates)
    for key in remove:
        features.pop(key, None)
    plan.features = features
    plan.save(update_fields=["features"])


def forwards(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug in AFFECTED_SLUGS:
        _patch_features(Plan, slug, {}, remove=PHANTOM_TRIAL_KEYS)


def backwards(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug in AFFECTED_SLUGS:
        _patch_features(Plan, slug, REINSTATED_ON_REVERSE)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0014_starter_bounded_by_outputs"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
