"""Create the Pilot plan and repair drifted / missing parcel limits.

Plan limits live in `Plan.features` (a JSONField) — they are DATA, not code. `create_plans` skips
any plan that already exists, so editing that command does not repair a row that has drifted.
Three defects, all verified against the dev database on 2026-08-07:

1. **No pilot plan exists at all.** October onboards free pilots, but a real mid-size California
   orchard maps one block to one Parcel and so needs 15-25 parcels and ~20 productions a year.
   Starter allows 1 and 1, enforcement is a hard 403 (`subscriptions/permissions.py`), and no
   exemption flag exists anywhere in the codebase. A pilot could not complete onboarding.

2. **`basic-monthly` / `basic-yearly` carry `max_parcels_per_establishment = 1`** while
   `create_plans.py` and the CLAUDE.md pricing table both say **2**. Basic has been shipping half
   its advertised parcel allowance.

3. **Legacy `standard` ($49) and `enterprise` ($499) are missing limit keys entirely.**
   `company/models.py` reads all three count limits with `default=0` (lines 110, 131, 160), so an
   absent key means "zero allowed", not "unlimited". `standard` had no
   `max_parcels_per_establishment`; `enterprise` had none of the three, so on the $499 plan a
   customer could not create a farm, a parcel, or a production. Latent today (zero subscriptions),
   live the moment somebody lands there.
"""

from django.db import migrations

PILOT_SLUG = "pilot"

# Mirrors `pilot_features` in subscriptions/management/commands/create_plans.py — see that file
# for why price=0, slug != "starter" and status "active" are each load-bearing.
PILOT_FEATURES = {
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

# Authoritative per-slug count limits, matching create_plans.py and the CLAUDE.md pricing table.
# -1 means unlimited.
#
# All THREE keys are repaired, not just parcels: company/models.py reads every one of them with
# `default=0` (lines 110, 131, 160), so a missing key silently means "zero allowed", not
# "unlimited". The legacy $499 `enterprise` row was missing max_productions_per_year and
# max_establishments as well — it could not have created a farm or a production either.
#
# monthly_scan_limit (default 5000) and storage_limit_gb (default 10) are deliberately NOT
# repaired here: their fallbacks are non-zero, so absence degrades rather than blocks.
# Slugs that create_plans.py owns. The seed command is authoritative for these, so a value that
# disagrees with it has DRIFTED and is overwritten — that is the whole point for basic-*, which
# shipped 1 parcel against an advertised 2.
MANAGED_LIMITS = {
    "starter": {"max_establishments": 1, "max_parcels_per_establishment": 1, "max_productions_per_year": 1},
    "basic-monthly": {"max_establishments": 1, "max_parcels_per_establishment": 2, "max_productions_per_year": 3},
    "basic-yearly": {"max_establishments": 1, "max_parcels_per_establishment": 2, "max_productions_per_year": 3},
    "standard-monthly": {"max_establishments": 2, "max_parcels_per_establishment": 2, "max_productions_per_year": 4},
    "standard-yearly": {"max_establishments": 2, "max_parcels_per_establishment": 2, "max_productions_per_year": 4},
    "corporate-monthly": {"max_establishments": 4, "max_parcels_per_establishment": 4, "max_productions_per_year": 6},
    "corporate-yearly": {"max_establishments": 4, "max_parcels_per_establishment": 4, "max_productions_per_year": 6},
    "enterprise-monthly": {
        "max_establishments": -1,
        "max_parcels_per_establishment": -1,
        "max_productions_per_year": -1,
    },
    "enterprise-yearly": {
        "max_establishments": -1,
        "max_parcels_per_establishment": -1,
        "max_productions_per_year": -1,
    },
}

# Legacy rows create_plans.py does not produce, so nothing is authoritative about their values.
# These are FILL-ONLY: an absent key becomes 0 at read time and blocks creation entirely, which
# must be fixed — but a key that is already set is somebody's deliberate configuration and is left
# alone. Overwriting here would mean clobbering production values with numbers observed in dev.
LEGACY_FILL_ONLY_LIMITS = {
    "standard": {"max_establishments": 2, "max_parcels_per_establishment": 2, "max_productions_per_year": 4},
    "enterprise": {"max_establishments": -1, "max_parcels_per_establishment": -1, "max_productions_per_year": -1},
}


def repair_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    Plan.objects.update_or_create(
        slug=PILOT_SLUG,
        defaults={
            "name": "Pilot",
            "description": (
                "Free pilot programme - unlimited farms, parcels and productions, "
                "white-glove onboarding"
            ),
            "price": 0,
            "interval": "monthly",
            "features": PILOT_FEATURES,
            "stripe_price_id": None,
            "is_active": True,
        },
    )

    for plan in Plan.objects.all():
        managed = MANAGED_LIMITS.get(plan.slug)
        legacy = LEGACY_FILL_ONLY_LIMITS.get(plan.slug)
        if not managed and not legacy:
            continue

        features = dict(plan.features or {})
        changed = False

        # Managed slugs: overwrite drift.
        for key, value in (managed or {}).items():
            if features.get(key) != value:
                features[key] = value
                changed = True

        # Legacy slugs: only supply what is missing.
        for key, value in (legacy or {}).items():
            if key not in features:
                features[key] = value
                changed = True

        if changed:
            plan.features = features
            plan.save(update_fields=["features"])


def unrepair(apps, schema_editor):
    """Remove the Pilot plan; leave repaired limits alone.

    Reverting the limits would restore states that are actively broken (Basic at half its
    advertised allowance, legacy plans unable to create any parcel), so this deliberately only
    undoes the additive part. The Pilot plan is only removed when nothing is subscribed to it —
    deleting a plan out from under a live pilot would null their subscription_plan and 403 every
    creation in the app.
    """
    Plan = apps.get_model("subscriptions", "Plan")
    pilot = Plan.objects.filter(slug=PILOT_SLUG).first()
    if not pilot:
        return
    # `pending_plan` is SET_NULL, so unlike `plan` (PROTECT) it would NOT stop the delete — a
    # scheduled change to Pilot would silently become "no pending plan" instead.
    in_use = pilot.subscriptions.exists() or pilot.pending_subscriptions.exists()
    if not in_use:
        pilot.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0007_subscriptionmonthlysnapshot_subscriptionevent_and_more"),
    ]

    operations = [
        migrations.RunPython(repair_plans, unrepair),
    ]
