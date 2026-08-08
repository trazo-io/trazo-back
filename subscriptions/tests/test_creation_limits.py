"""Subscription creation limits — the path that gates every pilot onboarding.

Before 2026-08-07 this had **zero** test coverage. The only two tests that mentioned parcel
limits (`product/tests/test_models.py:844`, `company/tests/test_models.py:384`) were stale and
raised `TypeError`: they passed `max_parcels_per_establishment` as a model kwarg, but limits live
in `Plan.features` JSON. One of them literally commented that the 4th-parcel block was untested.

Enforcement is a hard `HTTP 403` from `subscriptions/permissions.py`, so any defect here is the
difference between a farm onboarding and a farm bouncing off the product.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone


def _plan(slug, **limits):
    from subscriptions.models import Plan

    features = {
        "max_establishments": 1,
        "max_parcels_per_establishment": 1,
        "max_productions_per_year": 1,
    }
    features.update(limits)
    plan, _ = Plan.objects.update_or_create(
        slug=slug,
        defaults={
            "name": slug,
            "description": slug,
            "price": 0,
            "interval": "monthly",
            "features": features,
            "is_active": True,
        },
    )
    return plan


def _company_on(plan, *, status="active", period_start=None):
    from company.models import Company
    from subscriptions.models import Subscription

    company = Company.objects.create(name=f"Co for {plan.slug}")
    Subscription.objects.create(
        company=company,
        plan=plan,
        status=status,
        current_period_start=period_start or (timezone.now() - timedelta(days=5)),
        current_period_end=timezone.now() + timedelta(days=25),
    )
    company.refresh_from_db()
    return company


def _farm(company, name="Home Ranch"):
    from company.models import Establishment

    return Establishment.objects.create(name=name, company=company, country="US", state="CA")


def _parcel(farm, name):
    from product.models import Parcel

    return Parcel.objects.create(name=name, establishment=farm, area=10.0)


class ParcelLimitTests(TestCase):
    def test_blocks_at_a_finite_limit(self):
        company = _company_on(_plan("t-two-parcels", max_parcels_per_establishment=2))
        farm = _farm(company)
        self.assertTrue(company.can_create_parcel(farm))
        _parcel(farm, "A")
        self.assertTrue(company.can_create_parcel(farm))
        _parcel(farm, "B")
        # This is the assertion the stale test admitted was never written.
        self.assertFalse(company.can_create_parcel(farm))

    def test_unlimited_plan_never_blocks_even_at_orchard_scale(self):
        # A real mid-size CA orchard maps one block to one Parcel: 15-25 parcels is normal.
        company = _company_on(_plan("t-unlimited-parcels", max_parcels_per_establishment=-1))
        farm = _farm(company)
        for i in range(25):
            _parcel(farm, f"Block {i}")
        self.assertTrue(company.can_create_parcel(farm))

    def test_missing_limit_key_blocks_rather_than_permitting(self):
        # `features.get(..., 0)` means an ABSENT key reads as zero. The legacy $499 enterprise row
        # was in exactly this state, so nobody on it could create anything.
        from subscriptions.models import Plan

        plan = _plan("t-no-parcel-key")
        plan.features = {"max_establishments": 1, "max_productions_per_year": 1}
        plan.save(update_fields=["features"])
        Plan.objects.filter(pk=plan.pk).update(features=plan.features)
        company = _company_on(plan)
        self.assertFalse(company.can_create_parcel(_farm(company)))

    def test_no_subscription_plan_blocks(self):
        from company.models import Company

        company = Company.objects.create(name="No subscription")
        self.assertFalse(company.can_create_parcel(_farm(company)))

    def test_a_canceled_subscription_blocks_everything(self):
        # `subscription_plan` resolves only for active/trialing. This is what made the 14-day
        # Starter trial expiry so destructive: the account kept working right up until it didn't.
        company = _company_on(_plan("t-canceled", max_parcels_per_establishment=5), status="canceled")
        self.assertIsNone(company.subscription_plan)
        self.assertFalse(company.can_create_parcel(_farm(company)))


class ProductionQuotaTests(TestCase):
    """The quota must key off something the customer cannot edit."""

    def _production(self, farm, name, *, start_date=None):
        from history.models import History
        from product.models import Parcel

        parcel = Parcel.objects.filter(establishment=farm).first() or _parcel(farm, "P1")
        return History.objects.create(parcel=parcel, name=name, start_date=start_date)

    def test_blocks_at_the_limit(self):
        company = _company_on(_plan("t-two-prods", max_productions_per_year=2))
        farm = _farm(company)
        self.assertTrue(company.can_create_production())
        self._production(farm, "one")
        self._production(farm, "two")
        self.assertFalse(company.can_create_production())

    def test_backdating_start_date_no_longer_evades_the_quota(self):
        # THE regression. The quota counted `start_date >= Jan 1`, and `start_date` is supplied by
        # the farmer — so dating a production to 31 December made it free. In dev, 137 rows sat
        # before the window and were invisible to the count.
        company = _company_on(_plan("t-backdate", max_productions_per_year=1))
        farm = _farm(company)
        self._production(farm, "backdated", start_date=timezone.now() - timedelta(days=400))
        self.assertFalse(
            company.can_create_production(),
            "a backdated production still counts — the quota keys off created_at, not start_date",
        )

    def test_a_null_start_date_still_counts(self):
        # Previously uncountable: `start_date__gte` excludes NULL, so a production with no start
        # date was permanently invisible to the quota.
        company = _company_on(_plan("t-null-start", max_productions_per_year=1))
        farm = _farm(company)
        self._production(farm, "undated", start_date=None)
        self.assertFalse(company.can_create_production())

    def test_productions_created_in_a_previous_year_do_not_count(self):
        # The window is the calendar year. Deliberately NOT the subscription's
        # `current_period_start`: that is the BILLING period, so on a monthly plan it is ~30 days,
        # and a limit named `max_productions_per_year` would reset every month — 3/year would
        # silently become 36/year.
        from history.models import History

        company = _company_on(_plan("t-prev-year", max_productions_per_year=1))
        farm = _farm(company)
        old = self._production(farm, "last season")

        start_of_year = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        History.objects.filter(pk=old.pk).update(created_at=start_of_year - timedelta(days=1))
        self.assertTrue(company.can_create_production())

    def test_a_production_created_this_year_counts_regardless_of_billing_period(self):
        # Guards the regression directly: with a billing-period window, a production created
        # before the current month would have fallen outside the count and freed up quota.
        from history.models import History

        company = _company_on(
            _plan("t-billing-window", max_productions_per_year=1),
            period_start=timezone.now() - timedelta(days=2),
        )
        farm = _farm(company)
        created = self._production(farm, "earlier this year")

        start_of_year = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        # Somewhere earlier in the same calendar year, but before the billing period started.
        earlier = max(start_of_year, timezone.now() - timedelta(days=45))
        History.objects.filter(pk=created.pk).update(created_at=earlier)
        self.assertFalse(
            company.can_create_production(),
            "a production from earlier in the calendar year must still count against the annual limit",
        )

    def test_unlimited_plan_never_blocks(self):
        company = _company_on(_plan("t-unlimited-prods", max_productions_per_year=-1))
        farm = _farm(company)
        for i in range(20):
            self._production(farm, f"season {i}")
        self.assertTrue(company.can_create_production())


class EstablishmentLimitTests(TestCase):
    def test_blocks_at_the_limit(self):
        company = _company_on(_plan("t-one-farm", max_establishments=1))
        _farm(company, "First")
        self.assertFalse(company.can_create_establishment())

    def test_unlimited_never_blocks(self):
        company = _company_on(_plan("t-many-farms", max_establishments=-1))
        for i in range(6):
            _farm(company, f"Farm {i}")
        self.assertTrue(company.can_create_establishment())
