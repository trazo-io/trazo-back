"""Take Enterprise off the self-serve shelf.

The 2026-08-07 restructure (0009) settled the lineup as Starter (free) + Compliance $249/yr
+ "Enterprise — talk to us", but left both enterprise rows active. Because `PlanViewSet` is
AllowAny and serves every active non-pilot plan, the public API kept OFFERING Enterprise at
$299/month — 14x the $249/YEAR tier and 20-30x the category (COG Pro $99-179/yr, Quick
Organics $150/yr) — and the checkout path (`self_serve_plans().get(id=...)`) would have
accepted it. Same lesson as the blockchain withdrawal: retiring a product in strategy is not
retiring it in DATA.

An enterprise conversation is a human one (multiple farms, packer/marketer programs), so the
pricing surfaces now show a contact card instead of a price. Deactivate rather than delete:
`Subscription.plan` is PROTECT, and nobody is on these rows (zero users, Stripe on test keys).

`create_plans` seeds both enterprise entries `is_active=False` from the same date so a fresh
environment matches a migrated one.
"""

from django.db import migrations

ENTERPRISE_SLUGS = ["enterprise-monthly", "enterprise-yearly"]


def retire_enterprise(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=ENTERPRISE_SLUGS).update(is_active=False)


def restore_enterprise(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=ENTERPRISE_SLUGS).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0011_pilot_mirrors_compliance"),
    ]

    operations = [
        migrations.RunPython(retire_enterprise, restore_enterprise),
    ]
