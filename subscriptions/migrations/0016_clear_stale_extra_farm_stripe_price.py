"""Detach Extra Farm from the Stripe price that still bills $30/month.

WHY
---
A Stripe Price is IMMUTABLE. The amount and the recurring interval live on the price
object, not on the product, so changing what something costs means minting a NEW price —
there is no field to update.

Migration 0014 repriced Extra Farm from $30/MONTH to $149/YEAR. It changed `AddOn.price`
and `AddOn.interval`. It did not, and could not, touch Stripe: a data migration must not
make network calls, and there is no US entity or live Stripe account to call anyway. The
row kept `stripe_price_id` pointing at the price minted before the change.

`create_plans.create_addons` then made that permanent. Its guard was "if the add-on
already has a `stripe_price_id`, skip it" — an optimisation that reads as caching and
behaves as a freeze. Every subsequent seed left the stale id in place.

So the row published one price and carried another:

    AddOn.price     = 149.00        AddOn.interval = "yearly"     <- what the UI renders
    stripe_price_id = price_1T4tat…                               <- $30/month, recurring

The moment `PAYMENTS_ENABLED` flips true, the add-on card says "$149.00 per year", the
checkout charges $30 every month, and farm #2 costs $360/yr against a $249/yr plan. That
is the precise defect 0014 exists to remove, alive in the one layer nobody reads.

WHAT THIS DOES
--------------
Sets `stripe_price_id = NULL` on `extra-establishment`.

NULL is the correct value, not a placeholder for one. It is the honest statement that no
verified Stripe price backs this add-on, and it converts a silent mischarge into a loud
refusal: `SubscriptionViewSet.add_addon` now returns 409 with an explanatory message when
the id is missing, rather than handing Stripe a price line it cannot price correctly.

The id is restored on the correct path, not by hand: with `STRIPE_SECRET_KEY` set,
`create_plans` reads the live price, compares amount and interval against this file, mints
a replacement on the same product when they disagree, archives the old one and repoints
the row (`_addon_price_drift` / `_reprice_addon`). An unreadable price counts as drift —
a failed API call is not evidence that a price is correct.

SCOPE
-----
`extra-establishment` only. It is the sole ACTIVE add-on and the only one 0014 repriced.
The four inactive rows (`extra-parcel`, `extra-production`, `extra-storage`,
`blockchain-verification`) keep their ids: they are unsellable, and a retired row is still
a record of what it was.

NO SUBSCRIBERS ARE AFFECTED. Zero SubscriptionAddOn rows exist, Stripe runs on test keys
and payments are disabled in the app.
"""

from django.db import migrations

STALE_PRICE_SLUGS = ("extra-establishment",)


def clear_stale_price_ids(apps, schema_editor):
    AddOn = apps.get_model("subscriptions", "AddOn")
    AddOn.objects.filter(slug__in=STALE_PRICE_SLUGS).update(stripe_price_id=None)


def noop_reverse(apps, schema_editor):
    """Deliberately irreversible in effect.

    Reversing would mean re-attaching an id this migration exists to disown, and the
    correct id is not knowable here — it is whatever `create_plans` mints against the live
    Stripe account. Restoring the OLD id would restore the mischarge. Leaving NULL on the
    way back is the safe direction; re-run `create_plans` with a Stripe key to repopulate.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0015_strip_phantom_compliance_trial"),
    ]

    operations = [
        migrations.RunPython(clear_stale_price_ids, noop_reverse),
    ]
