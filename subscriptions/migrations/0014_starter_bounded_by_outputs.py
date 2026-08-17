"""Move Starter's wall from the INPUT (one production a year) to the OUTPUT (certifier documents),
and reprice the Extra Farm add-on from $30/month to $149/year.

WHY THE STARTER WALL MOVED
--------------------------
`max_productions_per_year: 1`. A production is a crop cycle; the ICP — a mid-size California
wholesale orchard — runs roughly twenty a year. Parcels were already unlimited, on purpose, so a
grower could model all twenty blocks and then hit a hard 403 at production #2: the cap bit at the
exact moment the farm started generating the records the product exists to produce. Nobody can
evaluate a RECORDKEEPING tool on a single crop cycle, and a renewal needs a whole season.

Measured against the alternatives a California grower actually has in front of them, a one-cycle
cap is not a free tier, it is a demo: Quick Organics gives twelve months of the full product (live
and uncapped on their pricing page, checked 2026-08-14), farmOS is free and open source, and the
CCOF Foundation writes California growers' OSPs one-to-one for free.

So the tier is now bounded by what it can PRODUCE. Log everything, all season, at no cost. The OSP
renewal packet, the audit export, the CA PUR export and the tokenized certifier review link are
what Compliance buys, enforced in `subscriptions/gating.py` — a display-only flag would be a price
list, not a plan. That also puts the upgrade prompt on the certifier's renewal deadline, at the
moment a season of the farm's own records is already in the system, instead of on a timer we chose.

TWO CHANGES THAT ARE NOT COSMETIC
---------------------------------
* **Storage 2 GB -> 10 GB.** `subscriptions/storage_utils.py` REFUSES an upload once projected
  usage passes the limit. A season of photo evidence does not fit in 2 GB, so leaving it would have
  re-imposed the wall this migration removes, in a worse form: not a clear "upgrade to add another
  production" but a failed photo upload in the field.
* **`voice_recording` False -> True.** The measured barriers to farm software adoption are lack of
  time and labour (63-65%) and insufficient training (53%) ahead of up-front cost (44%). Gating the
  fastest gloves-on input path suppressed exactly the logging that produces the records that
  produce the upgrade. The paid tier sells the artifact, not the keyboard.

THE ADD-ON
----------
"Extra Farm" was $30/MONTH beside a $249/YEAR plan: $360 a year, so farm #2 cost 45% MORE than
farm #1. The marginal price rose with volume, and the operator it punished hardest was the
multi-farm grower — the largest, best-funded customer in the pipeline. It also mixed billing
periods on one invoice. Now $149/year, 60% of base.

`AddOn.interval` is a NEW FIELD. The period an add-on billed at previously existed only in Stripe:
`create_plans` passed an "interval" key to `stripe.Price.create` and then dropped it on the way
into the database, so the app rendered a bare "$30.00" and no surface could say which period it
meant. The three inactive add-ons are stamped "monthly" because that is what they were; a retired
row is still a record, and it should not start lying about itself on the way out.

NO SUBSCRIBERS ARE AFFECTED. Trazo has zero real users; this shapes what the first ones meet.
"""

from django.db import migrations, models

# Slug -> the exact key/value edits applied to Plan.features, and the values to restore on reverse.
STARTER_FORWARD = {
    "max_productions_per_year": -1,
    "storage_limit_gb": 10,
    "voice_recording": True,
    "compliance_exports": False,
}
STARTER_REVERSE = {
    "max_productions_per_year": 1,
    "storage_limit_gb": 2,
    "voice_recording": False,
}

STARTER_DESCRIPTION = (
    "Free forever. One farm, unlimited parcels, unlimited productions — log a whole season with "
    "no card and no expiry. Certifier documents are Compliance."
)
STARTER_DESCRIPTION_PREVIOUS = (
    "Free forever. One farm, unlimited parcels, one production a year — no card, no expiry."
)

COMPLIANCE_DESCRIPTION = (
    "Everything one certified farm needs for renewal season: the OSP renewal packet, the audit "
    "export, the CA PUR export and the certifier review link."
)
COMPLIANCE_DESCRIPTION_PREVIOUS = (
    "Everything one certified farm needs for renewal season: unlimited parcels and productions, "
    "the certifier packet, CA PUR export and the buyer page."
)

# Every plan that grants the exports. The four legacy tiers are RETIRED, not deleted, and each of
# them was PAID — omitting them would make `has_feature("compliance_exports")` return False and
# silently strip the packet, audit export, PUR export and certifier link from anyone still on one.
# There are no such subscribers today; that makes the correction cheap, not unnecessary.
PLANS_WITH_EXPORTS = [
    "compliance-yearly",
    "pilot",
    "basic-monthly",
    "basic-yearly",
    "standard-monthly",
    "standard-yearly",
    "corporate-monthly",
    "corporate-yearly",
    "enterprise-monthly",
    "enterprise-yearly",
]

EXTRA_FARM_DESCRIPTION = "Add an additional farm to your Compliance plan, billed yearly alongside it"
EXTRA_FARM_DESCRIPTION_PREVIOUS = "Add an additional farm beyond your plan limit"

# The period each add-on genuinely billed at before the field existed, from the definitions in
# `create_plans.create_addons` that were being handed to Stripe.
#
# `extra-storage` is the one that is NOT read off a definition: no version of `create_plans` in the
# tree defines it — the row predates them and survives only because `get_storage_limit_gb` and the
# effective-limits serializer still read it. It is stamped "monthly" rather than left on the field
# default because every other capacity add-on billed monthly, and it existed only while the
# monthly ladder was the whole lineup. It is inactive and unsellable either way; the point is that
# a retired row should carry the best-supported value rather than whichever one the schema
# happened to default to.
ADDON_INTERVALS = {
    "extra-establishment": "yearly",
    "extra-production": "monthly",
    "extra-parcel": "monthly",
    "blockchain-verification": "monthly",
    "extra-storage": "monthly",
}


def _patch_features(Plan, slug, updates, remove=()):
    """Read-modify-write one plan's JSON features. Missing plan is a no-op, not an error:
    a fresh database seeded by `create_plans` already carries the new values, and this
    migration must be able to run either before or after that seed."""
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
    AddOn = apps.get_model("subscriptions", "AddOn")

    _patch_features(Plan, "starter", STARTER_FORWARD)
    Plan.objects.filter(slug="starter").update(description=STARTER_DESCRIPTION)

    for slug in PLANS_WITH_EXPORTS:
        _patch_features(Plan, slug, {"compliance_exports": True})
    Plan.objects.filter(slug="compliance-yearly").update(description=COMPLIANCE_DESCRIPTION)

    for slug, interval in ADDON_INTERVALS.items():
        AddOn.objects.filter(slug=slug).update(interval=interval)

    AddOn.objects.filter(slug="extra-establishment").update(
        price="149.00",
        description=EXTRA_FARM_DESCRIPTION,
    )


def backwards(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    AddOn = apps.get_model("subscriptions", "AddOn")

    # `compliance_exports` is REMOVED rather than set False on the way back: the key did not exist
    # before this migration, and `has_feature` treats absent and False identically. Leaving a
    # False behind would look like a deliberate denial rather than a plan that predates the gate.
    _patch_features(Plan, "starter", STARTER_REVERSE, remove=("compliance_exports",))
    Plan.objects.filter(slug="starter").update(description=STARTER_DESCRIPTION_PREVIOUS)

    for slug in PLANS_WITH_EXPORTS:
        _patch_features(Plan, slug, {}, remove=("compliance_exports",))
    Plan.objects.filter(slug="compliance-yearly").update(description=COMPLIANCE_DESCRIPTION_PREVIOUS)

    AddOn.objects.filter(slug="extra-establishment").update(
        price="30.00",
        description=EXTRA_FARM_DESCRIPTION_PREVIOUS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0013_extra_farm_display_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="addon",
            name="interval",
            field=models.CharField(
                choices=[("monthly", "Monthly"), ("yearly", "Yearly")],
                default="yearly",
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
