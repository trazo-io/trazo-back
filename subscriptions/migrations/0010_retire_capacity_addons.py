"""Retire the per-parcel and per-production add-ons made meaningless by the Compliance tier.

WHY
---
0009 gave Starter unlimited parcels and gave Compliance unlimited parcels AND unlimited
productions. Two add-ons survived that change and still say `is_active=True`:

* `extra-parcel` ($25) — sells parcel capacity that BOTH live tiers now grant without limit.
* `extra-production` ($20) — sells production capacity Compliance already grants without limit.

An add-on that charges for something the plan already includes is not merely dead copy, it is a
billing defect: `/api/subscriptions/addons/` serves whatever is active, so the app would offer a
grower the chance to pay for capacity they already have.

This is the same trap as the blockchain add-on, which sat at `is_active=False` in data for four
months while both UIs kept rendering a hardcoded $15/mo offer. The lesson recorded there was that
withdrawing a product in DATA is not withdrawing it from the UI. The inverse is just as true and
is what this migration closes: leaving a row ACTIVE keeps the offer legitimate no matter what the
pricing page says, and one reseed is all it takes for a UI to start honouring it again.

WHAT IS LEFT ALONE
------------------
`extra-establishment` stays active. It is the one add-on that still means something under
per-farm pricing — a second farm is genuinely more product. It is NOT repriced here: it carries
$30 on a monthly cadence while the Compliance plan it would attach to is billed yearly, so the
$30 is not comparable to $249 and picking the annual number is a pricing decision, not a
migration. Until that is settled the pricing page publishes no add-on price and routes a
multi-farm grower to a conversation.

`extra-storage` is already inactive and stays that way.

No Stripe calls: there is no US entity, Stripe is disabled in production, and these rows carry no
live price object to archive. Deactivating is a local-row change only.
"""

from django.db import migrations

# Capacity the live tiers now grant without limit.
SUPERSEDED_BY_UNLIMITED = ["extra-parcel", "extra-production"]


def retire_capacity_addons(apps, schema_editor):
    AddOn = apps.get_model("subscriptions", "AddOn")
    AddOn.objects.filter(slug__in=SUPERSEDED_BY_UNLIMITED).update(is_active=False)


def restore_capacity_addons(apps, schema_editor):
    """Reactivate. Only coherent alongside a revert of 0009, which restores the finite limits."""
    AddOn = apps.get_model("subscriptions", "AddOn")
    AddOn.objects.filter(slug__in=SUPERSEDED_BY_UNLIMITED).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0009_compliance_tier"),
    ]

    operations = [
        migrations.RunPython(retire_capacity_addons, restore_capacity_addons),
    ]
