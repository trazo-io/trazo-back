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


class ProductionQuotaAsksTheRightCompany(TestCase):
    """A quota question is asked of the subscription that will be BILLED.

    Found by driving the real app 2026-08-19: the demo account works in two companies. The
    ACTIVE one sat on a retired `corporate-*` plan capped at 6 productions/year and already at
    6; the parcel belonged to the OTHER company (Compliance, unlimited). Starting a season
    answered 403 — `HasProductionCreationPermission` read the quota off `get_active_company()`
    while the view creates the production on `parcel.establishment.company`.

    The false negative is the visible half. The false POSITIVE is the one that matters: switch
    active company to any unlimited one and the exhausted company's cap is bypassed entirely.
    A limit defeated by a dropdown is not a limit.
    """

    def setUp(self):
        from unittest.mock import patch

        from company.models import Establishment
        from product.models import Parcel
        from subscriptions.permissions import HasProductionCreationPermission
        from users.models import User, WorksIn

        self.permission = HasProductionCreationPermission()
        self.user = User.objects.create_user(email="two.hats@trazo.test", password="x")
        self._patch = patch
        self.WorksIn = WorksIn

        self.capped = _company_on(_plan("legacy-corporate", max_productions_per_year=0))
        self.owner = _company_on(_plan("compliance-unlimited", max_productions_per_year=-1))
        for company in (self.capped, self.owner):
            WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)

        self.parcel = Parcel.objects.create(
            establishment=Establishment.objects.create(company=self.owner, name="Home Ranch"),
            name="Block A",
            area=5.0,
        )
        self.capped_parcel = Parcel.objects.create(
            establishment=Establishment.objects.create(company=self.capped, name="Capped Ranch"),
            name="Block Z",
            area=5.0,
        )

    def _request(self, parcel_id, active_company):
        from rest_framework.parsers import JSONParser
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        # Wrapped in a DRF Request on purpose: APIRequestFactory returns a plain Django
        # WSGIRequest, which has no `.data`. The permission class reads `request.data`, so an
        # unwrapped request tests nothing but its own AttributeError.
        request = Request(
            APIRequestFactory().post("/api/histories/start-production/", {"parcel_id": parcel_id}, format="json"),
            parsers=[JSONParser()],
        )
        request.user = self.user
        patcher = self._patch.object(type(self.user), "get_active_company", return_value=active_company)
        patcher.start()
        self.addCleanup(patcher.stop)
        return request

    def test_an_exhausted_active_company_does_not_block_another_companys_parcel(self):
        self.assertTrue(self.permission.has_permission(self._request(self.parcel.id, self.capped), view=None))

    def test_an_unlimited_active_company_does_not_unlock_an_exhausted_one(self):
        """The bypass — the half a false-negative-only fix would have left open."""
        self.assertFalse(self.permission.has_permission(self._request(self.capped_parcel.id, self.owner), view=None))

    def test_with_no_parcel_in_the_payload_it_falls_back_to_the_active_company(self):
        self.assertTrue(self.permission.has_permission(self._request("", self.owner), view=None))

    def test_a_garbage_parcel_id_defers_to_the_view_rather_than_403ing(self):
        """The view answers a specific 404 for a bad parcel; a permission class that refused
        first would replace it with a misleading "your plan has reached its maximum"."""
        self.assertTrue(self.permission.has_permission(self._request("not-a-number", self.owner), view=None))


class FarmAndParcelQuotasAskTheRightCompany(TestCase):
    """The same audit, applied to the two siblings of the production quota.

    `HasEstablishmentCreationPermission` is the worst of the three, because farms are the
    metric Trazo actually BILLS: Extra Farm is $149/yr and the Operation tier exists precisely
    to lift the farm cap. The permission asked `get_active_company()`, while
    `EstablishmentViewSet` has no `perform_create` override and `company` is a writable field
    on `UpdateEstablishmentSerializer` — so the row is created on whatever company the PAYLOAD
    names. Point active at a company with headroom, post `company: <exhausted company>`, and
    the farm cap is gone.

    `HasParcelCreationPermission` was bypass-SAFE by accident: it looked the establishment up
    through `company.establishment_set`, so a foreign establishment raised DoesNotExist. But it
    answered False for a legitimate multi-company user, and its bare `except Exception` turned
    every programming error into a polite "your plan does not allow this".
    """

    def setUp(self):
        from unittest.mock import patch

        from company.models import Establishment
        from subscriptions.permissions import HasEstablishmentCreationPermission, HasParcelCreationPermission
        from users.models import User, WorksIn

        self.farm_perm = HasEstablishmentCreationPermission()
        self.parcel_perm = HasParcelCreationPermission()
        self.user = User.objects.create_user(email="multi.co@trazo.test", password="x")
        self._patch = patch

        # Exhausted on BOTH metrics.
        self.capped = _company_on(_plan("capped-co", max_establishments=0, max_parcels_per_establishment=0))
        # Room on both.
        self.roomy = _company_on(_plan("roomy-co", max_establishments=-1, max_parcels_per_establishment=-1))
        for company in (self.capped, self.roomy):
            WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)

        self.capped_farm = Establishment.objects.create(company=self.capped, name="Capped Ranch")
        self.roomy_farm = Establishment.objects.create(company=self.roomy, name="Roomy Ranch")

    def _request(self, payload, active_company):
        from rest_framework.parsers import JSONParser
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        request = Request(
            APIRequestFactory().post("/api/whatever/", payload, format="json"),
            parsers=[JSONParser()],
        )
        request.user = self.user
        patcher = self._patch.object(type(self.user), "get_active_company", return_value=active_company)
        patcher.start()
        self.addCleanup(patcher.stop)
        return request

    # --- farms: the billed metric -------------------------------------------------
    def test_an_unlimited_active_company_does_not_unlock_an_exhausted_ones_farm_cap(self):
        """The bypass. Farms are what Extra Farm ($149/yr) and the Operation tier price."""
        request = self._request({"company": self.capped.id}, self.roomy)
        self.assertFalse(self.farm_perm.has_permission(request, view=None))

    def test_an_exhausted_active_company_does_not_block_a_farm_on_another_company(self):
        request = self._request({"company": self.roomy.id}, self.capped)
        self.assertTrue(self.farm_perm.has_permission(request, view=None))

    def test_with_no_company_in_the_payload_it_falls_back_to_the_active_company(self):
        self.assertTrue(self.farm_perm.has_permission(self._request({}, self.roomy), view=None))
        self.assertFalse(self.farm_perm.has_permission(self._request({}, self.capped), view=None))

    # --- parcels ------------------------------------------------------------------
    def test_an_unlimited_active_company_does_not_unlock_an_exhausted_ones_parcel_cap(self):
        request = self._request({"establishment": self.capped_farm.id}, self.roomy)
        self.assertFalse(self.parcel_perm.has_permission(request, view=None))

    def test_an_exhausted_active_company_does_not_block_a_parcel_on_another_company(self):
        """The false negative the old `company.establishment_set.get()` lookup produced."""
        request = self._request({"establishment": self.roomy_farm.id}, self.capped)
        self.assertTrue(self.parcel_perm.has_permission(request, view=None))

    def test_a_parcel_on_an_establishment_the_user_does_not_work_in_is_refused(self):
        from company.models import Company, Establishment

        stranger = Company.objects.create(name="Stranger Co")
        foreign_farm = Establishment.objects.create(company=stranger, name="Not Mine")
        request = self._request({"establishment": foreign_farm.id}, self.roomy)
        self.assertFalse(self.parcel_perm.has_permission(request, view=None))

    def test_a_farm_on_a_company_the_user_does_not_work_in_is_refused(self):
        from company.models import Company

        stranger = Company.objects.create(name="Stranger Co 2")
        request = self._request({"company": stranger.id}, self.roomy)
        self.assertFalse(self.farm_perm.has_permission(request, view=None))
