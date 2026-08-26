"""Test-support helpers for subscription state.

`require_compliance_exports` (subscriptions/gating.py) fails CLOSED: a company with no
subscription cannot generate certifier documents. That is the correct production behaviour — an
unknown plan must not be treated as a paid one — but it broke every pre-existing export test,
because those fixtures built a Company and an Establishment and never a Subscription. The
endpoints did not need a plan before, so nobody gave them one.

Patching each fixture by hand would spread the same six lines across suites in three apps and
guarantee they drift. This is the one place that says "put this company on the paid tier", so when
the paid tier changes shape the fixtures follow it.

Deliberately NOT in a `tests/` package: it is imported by tests in `history`, `certifications` and
`company`, and a helper that several apps depend on should not live inside one app's test tree.
"""

from datetime import timedelta

from django.utils import timezone

from .models import Plan, Subscription

COMPLIANCE_SLUG = "compliance-yearly"


def compliance_plan():
    """The paid tier, guaranteed to grant the exports.

    `get_or_create` because migrations 0009/0011/0014 already seed this row — a plain `create`
    raises UniqueViolation on a freshly built test database while passing under `--keepdb`, which
    is exactly the failure mode that hides in CI. The feature is then forced ON rather than
    assumed: a fixture that silently sat on a plan without `compliance_exports` would fail with a
    403 that looks like a permissions bug.
    """
    plan, _ = Plan.objects.get_or_create(
        slug=COMPLIANCE_SLUG,
        defaults={
            "name": "Compliance",
            "description": "Test fixture",
            "price": 249,
            "interval": "yearly",
            "is_active": True,
            # A realistic paid-tier shape, not `{}`.
            #
            # Migrations seed this row, so the create branch should never fire — but if it ever
            # does, an empty feature dict makes `get_feature_limit` fall back to 0 and
            # `can_create_establishment` / `can_create_parcel` return False. A fixture that calls
            # this helper and then creates a farm would fail on a limit it never set, three files
            # away from the cause.
            "features": {
                "max_establishments": 1,
                "max_parcels_per_establishment": -1,
                "max_productions_per_year": -1,
                "storage_limit_gb": 25,
                "compliance_exports": True,
            },
        },
    )
    # `(plan.features or {})` on BOTH reads. The guard used to be on the write only, so a row
    # with NULL features — which the column permits — raised AttributeError on the read one line
    # earlier, before the defensive write could help.
    if (plan.features or {}).get("compliance_exports") is not True:
        plan.features = {**(plan.features or {}), "compliance_exports": True}
        plan.save(update_fields=["features"])
    return plan


def grant_compliance_exports(company):
    """Put `company` on an active Compliance subscription and return it.

    `update_or_create` on the company, so calling this twice — or on a company a fixture already
    subscribed — moves the plan instead of raising on the OneToOne.
    """
    Subscription.objects.update_or_create(
        company=company,
        defaults={
            "plan": compliance_plan(),
            "status": "active",
            "current_period_start": timezone.now() - timedelta(days=5),
            "current_period_end": timezone.now() + timedelta(days=360),
        },
    )
    company.refresh_from_db()
    return company
