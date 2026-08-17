"""One `SubscriptionAddOn` row per (subscription, add-on), enforced by the database.

WHY
---
Quantity is the multiplier. Two of something is `quantity=2`, never two rows. Both writers
already relied on that and neither could guarantee it:

* the Stripe webhook does `SubscriptionAddOn.objects.get_or_create(...)` and then increments
  the quantity it finds;
* `SubscriptionViewSet.add_addon` does `update_or_create(...)`.

Both are SELECT-then-INSERT. Two requests that interleave between the two statements both
insert, and nothing rejected the second row. `Company.can_create_establishment()` SUMS every
matching row:

    extra = sum(a.quantity for a in subscription.addons.filter(addon__slug="extra-establishment"))

so a duplicated row is not a cosmetic double-entry in an admin list — it silently grants
capacity that was never bought. A get-or-create pattern is a uniqueness ASSUMPTION; only a
constraint is a uniqueness guarantee.

COLLAPSING FIRST
----------------
The constraint cannot be added over existing duplicates, and dropping the extras would throw
away quantity a customer may have paid for. So duplicates are MERGED into the oldest row:
quantities are summed, and the `stripe_item_id` is taken from the first row that has one —
that is the item Stripe is actually billing, and an id is more useful than a NULL when
reconciling. The survivors are the oldest rows because `created_at` is what any invoice or
support conversation will be anchored to.

Reverse drops the constraint and does not un-merge. Splitting a summed quantity back into
rows would be inventing history: nothing records which row contributed what.

NO SUBSCRIBERS ARE AFFECTED TODAY. There are zero SubscriptionAddOn rows — Trazo has no
paying customers and payments are disabled. That makes the merge code cheap to get right,
not unnecessary: it has to be correct before the first add-on is ever sold, because that is
the last moment it can be added without a customer-visible reconciliation.
"""

from django.db import migrations, models


def collapse_duplicate_addons(apps, schema_editor):
    SubscriptionAddOn = apps.get_model("subscriptions", "SubscriptionAddOn")

    seen = {}
    duplicates = []
    # Oldest first, so the first row of each pair is the one that survives.
    for row in SubscriptionAddOn.objects.order_by("created_at", "pk").iterator():
        key = (row.subscription_id, row.addon_id)
        keeper = seen.get(key)
        if keeper is None:
            seen[key] = row
            continue
        keeper.quantity = (keeper.quantity or 0) + (row.quantity or 0)
        if not keeper.stripe_item_id and row.stripe_item_id:
            keeper.stripe_item_id = row.stripe_item_id
        duplicates.append(row.pk)

    for keeper in seen.values():
        keeper.save(update_fields=["quantity", "stripe_item_id"])

    if duplicates:
        SubscriptionAddOn.objects.filter(pk__in=duplicates).delete()


def noop_reverse(apps, schema_editor):
    """Merged rows are not split back apart — nothing records which row contributed what."""


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0016_clear_stale_extra_farm_stripe_price"),
    ]

    operations = [
        migrations.RunPython(collapse_duplicate_addons, noop_reverse),
        migrations.AddConstraint(
            model_name="subscriptionaddon",
            constraint=models.UniqueConstraint(
                fields=("subscription", "addon"),
                name="unique_addon_per_subscription",
            ),
        ),
    ]
