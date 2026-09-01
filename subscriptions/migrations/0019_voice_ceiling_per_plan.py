"""Give each plan its own daily voice ceiling, instead of one number for everybody.

WHY
---
Voice is ON for the free tier and should stay on. Migration 0014 turned it on for exactly the
right reason: the measured barriers to farm software adoption are lack of time and labour (63-65%)
and insufficient training (53%) ahead of up-front cost (44%), so gating the fastest gloves-on input
path suppresses the logging that produces the records that produce the upgrade. The paid tier sells
the artifact, not the keyboard.

But voice is also the ONE entitlement in that dict which costs money per use. Every other line —
parcels, productions, storage — is bounded by something the farm already owns. A voice session
streams metered audio to a transcription vendor and then calls a model, so it converts directly
into a bill, and until now every tier shared a single ceiling read from an environment variable
(`VOICE_DAILY_SESSION_LIMIT = 200`). MEASURED 2026-08-31 from the code: ~1,322 input tokens per
parse and a 90-second cap per recording, which is roughly $0.0025 a session at typical length and
about $0.01 at the cap. So the shared ceiling bounded a company paying NOTHING at the same place as
one paying $1,200 — on the order of $700 a year of usage against $0 of revenue, per free account.

That is not a hypothetical abuse case so much as a missing decision: nobody chose 200 for the free
tier, it was simply the only number there was.

THE NUMBERS, AND WHY THEY ARE NOT TIGHTER
-----------------------------------------
* **Starter 50.** Five times a heavy logging day (`carbon/services/voice_budget.py`: "a heavy
  logging day is tens of entries, not hundreds"). A ceiling that bites a real grower during harvest
  would be self-defeating — harvest is exactly when the season's records get made and the certifier
  packet starts to matter. This bites a loop, not a farm.
* **Compliance 200.** The number the system already ran at, now named by the plan rather than by a
  deploy variable. One farm.
* **Operation 1,000.** The budget is counted PER COMPANY and this tier is unlimited FARMS under one
  company, so 200 could genuinely bind ten farms logging the same week. Five times Compliance.
* **Pilot** inherits Compliance in `create_plans`, which is what a comped Compliance should do.
* **The retired ladder** (basic/standard/corporate/enterprise) is deliberately NOT touched. Those
  slugs were deactivated as products but are LIVE AS CONTRACTS, and `daily_limit()` falls back to
  the environment default for any plan that does not name the key — so their behaviour is exactly
  what it was this morning. Changing a live contract's entitlement in a migration about free-tier
  cost control would be the wrong place to do it.

`-1` means unlimited here, the same as it does for `max_establishments` and
`max_parcels_per_establishment`; `daily_limit()` and the `limit <= 0` branch in
`consume_voice_session` already agree on that reading.
"""

from django.db import migrations

VOICE_CEILINGS = {
    "starter": 50,
    "compliance-yearly": 200,
    "operation-yearly": 1000,
    "pilot": 200,
}


def _patch_features(Plan, slug, updates, remove=()):
    """Read-modify-write one plan's JSON features. A missing plan is a no-op, not an error: a
    fresh database seeded by `create_plans` already carries these values, and this migration has
    to run either before or after that seed."""
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
    for slug, ceiling in VOICE_CEILINGS.items():
        _patch_features(Plan, slug, {"voice_daily_sessions": ceiling})


def backwards(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    # REMOVED rather than set back to 200. The key did not exist before this migration, and
    # `daily_limit` treats an absent key as "use the environment default" — which is precisely the
    # previous behaviour. Writing 200 back would look like a plan that had chosen its ceiling.
    for slug in VOICE_CEILINGS:
        _patch_features(Plan, slug, {}, remove=("voice_daily_sessions",))


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0018_cancellation_reason_capture"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
