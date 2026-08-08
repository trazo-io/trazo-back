"""Replace the monthly SaaS ladder with a single annual Compliance tier.

WHY THE LADDER IS WRONG FOR THIS MARKET
---------------------------------------
Verified competitor pricing (primary sources, 2026-08): COG Pro **$99 / $155 / $179 per year**
(dying 2026-12-31), Quick Organics **$150/yr** and frequently certifier-paid. Trazo was asking
**$69–299 per MONTH** — $828–3,588/yr, i.e. 5–8x the category. A COG Pro refugee paying $155/yr
does not sign for $828, so the whole forced-migration thesis died on the pricing page.

WHY PER-PARCEL IS THE WRONG METRIC
----------------------------------
A Parcel IS a block (settled 2026-08-07: certifiers flatten to one location token, there is no
sub-field tier). So parcel count measures farm GEOMETRY, not value — a 20-block and a 4-block
orchard of the same acreage paid 5x differently for identical output.

Worse, it contradicts the product's own thesis. Trazo's argument is "log more -> higher score ->
premium positioning". Charging per parcel means structuring your records properly costs more,
which is the same perverse incentive the transparency-first pivot rejected when it refused
carbon-first scoring. Reintroducing it on the billing side would be self-defeating.

What a farm actually buys — the certifier packet, the PUR export, the buyer page, the Common OSP
§ 11 draft — is per-FARM. One certificate, one OSP, one renewal. That is also the unit growers
already think in, because certification itself is priced that way.

WHAT THIS DOES
--------------
* Starter stays free but becomes USABLE: unlimited parcels instead of 1. A one-parcel free tier
  cannot demonstrate anything to a 20-block orchard — the trial was structurally incapable of
  showing value to the exact ICP it was meant to attract.
* Adds `compliance-yearly` at $249/yr: 1 farm, unlimited parcels and productions.
* Deactivates basic/standard/corporate (monthly and yearly). NOT deleted — `Subscription.plan` is
  `PROTECT`, and deleting a plan somebody references would fail. Nobody is on them (zero users,
  Stripe on test keys), so this is the cheapest possible moment to do it.
* Enterprise and the internal `pilot` plan are untouched.

NO STRIPE. There is no US entity yet and Stripe is disabled in production, so this writes local
rows only and leaves `stripe_price_id` NULL. The pricing page CTAs are "Start free" (signup) and
"Contact Sales" (mailto) — no checkout — so a published price cannot lead anyone to a dead
payment flow.
"""

from django.db import migrations

COMPLIANCE_SLUG = "compliance-yearly"

COMPLIANCE_FEATURES = {
    "max_establishments": 1,
    "max_parcels_per_establishment": -1,
    "max_productions_per_year": -1,
    "establishment_full_description": True,
    "monthly_scan_limit": -1,
    "storage_limit_gb": 25,
    "support_response_time": 24,
    "trial_no_card_days": 14,
    "trial_with_card_days": 14,
    "priority_support": True,
    "dedicated_support": False,
    "voice_recording": True,
    "ai_event_templates": True,
}

# Free tier: still one farm and one season, but every block of it.
STARTER_PARCELS_UNLIMITED = -1

RETIRED_SLUGS = [
    "basic-monthly",
    "basic-yearly",
    "standard-monthly",
    "standard-yearly",
    "corporate-monthly",
    "corporate-yearly",
    "standard",  # legacy $49 row
]


def apply_pricing(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    Plan.objects.update_or_create(
        slug=COMPLIANCE_SLUG,
        defaults={
            "name": "Compliance",
            "description": (
                "Everything one certified farm needs for renewal season: unlimited parcels and "
                "productions, the certifier packet, CA PUR export and the buyer page."
            ),
            "price": 249,
            "interval": "yearly",
            "features": COMPLIANCE_FEATURES,
            "stripe_price_id": None,
            "is_active": True,
        },
    )

    starter = Plan.objects.filter(slug="starter").first()
    if starter:
        features = dict(starter.features or {})
        features["max_parcels_per_establishment"] = STARTER_PARCELS_UNLIMITED
        starter.features = features
        starter.save(update_fields=["features"])

    # Deactivate rather than delete: Subscription.plan is PROTECT.
    Plan.objects.filter(slug__in=RETIRED_SLUGS).update(is_active=False)


def revert_pricing(apps, schema_editor):
    """Reactivate the old ladder and put Starter back to one parcel.

    The Compliance plan is removed only when nothing references it — deleting a plan out from
    under a subscriber would null their `subscription_plan` and 403 every creation in the app.
    """
    Plan = apps.get_model("subscriptions", "Plan")

    Plan.objects.filter(slug__in=RETIRED_SLUGS).update(is_active=True)

    starter = Plan.objects.filter(slug="starter").first()
    if starter:
        features = dict(starter.features or {})
        features["max_parcels_per_establishment"] = 1
        starter.features = features
        starter.save(update_fields=["features"])

    compliance = Plan.objects.filter(slug=COMPLIANCE_SLUG).first()
    if compliance and not compliance.subscriptions.exists() and not compliance.pending_subscriptions.exists():
        compliance.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0008_pilot_plan_and_parcel_limit_repair"),
    ]

    operations = [
        migrations.RunPython(apply_pricing, revert_pricing),
    ]
