"""Reshape `pilot` to be Compliance comped, instead of a tier nobody can buy.

THE DEFECT
----------
`pilot` granted unlimited farms, 50 GB and 12hr support. Compliance — the only plan actually for
sale — grants 1 farm, 25 GB and 24hr support. So an October pilot spent the season using a product
that does not exist on the price list, and the April conversion asked them to start paying AND
give up three things at the same moment.

The storage half was a hard blocker rather than a bad feeling. `subscriptions/storage_utils.py`
refuses an upload once projected usage passes the limit, so a pilot who logged 40 GB of photo
evidence across a season could not move onto Compliance's 25 GB without deleting their own
records — during renewal season, which is the worst possible week to ask a grower to delete
documentation.

It also quietly invalidated the measurement. The Apr 30 conversion verdict in the October plan is
meant to answer "will a farm pay for Trazo". Run on unlimited-everything it answers "will a farm
pay for a tier we do not sell", which is not a question anyone needs answered.

WHAT THIS DOES
--------------
Copies the live Compliance feature set onto `pilot`, preserving exactly three pilot-only keys:

  * `is_pilot: True`         — what `self_serve_plans()` filters on to keep a free unlimited plan
                               off the public AllowAny plan list.
  * `trial_*_days: 0`        — a pilot is not a trial. It ends by agreement on the grower's
                               certifier renewal date, recorded per-company on the subscription by
                               `provision_pilot`, not by a timer that cancels the account.

Derived from the Compliance ROW rather than a hardcoded copy, so this cannot encode a stale
snapshot of a tier that has been edited since.

NOT A PRICE CHANGE. Pilot stays $0, so `mrr_for()` still books zero and pilots never appear as
revenue that does not exist.
"""

from django.db import migrations

PILOT_ONLY_KEYS = {
    "is_pilot": True,
    "trial_no_card_days": 0,
    "trial_with_card_days": 0,
}

# What pilot granted before, for the reverse path.
PREVIOUS_PILOT_FEATURES = {
    "max_establishments": -1,
    "max_parcels_per_establishment": -1,
    "max_productions_per_year": -1,
    "establishment_full_description": True,
    "monthly_scan_limit": -1,
    "storage_limit_gb": 50,
    "support_response_time": 12,
    "trial_no_card_days": 0,
    "trial_with_card_days": 0,
    "priority_support": True,
    "dedicated_support": True,
    "voice_recording": True,
    "ai_event_templates": True,
    "is_pilot": True,
}


def mirror_compliance(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    pilot = Plan.objects.filter(slug="pilot").first()
    compliance = Plan.objects.filter(slug="compliance-yearly").first()

    if not pilot:
        return
    if not compliance:
        # 0009 creates it; a database without it is mid-upgrade, and guessing a feature set here
        # would bake in exactly the stale snapshot this migration exists to avoid.
        return

    pilot.features = {**(compliance.features or {}), **PILOT_ONLY_KEYS}
    pilot.save(update_fields=["features"])


def restore_unlimited_pilot(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug="pilot").update(features=PREVIOUS_PILOT_FEATURES)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0010_retire_capacity_addons"),
    ]

    operations = [
        migrations.RunPython(mirror_compliance, restore_unlimited_pilot),
    ]
