import logging
from datetime import datetime as dt
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import requests
import stripe
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from company.models import STARTER_PLAN_SLUG, Company
from company.serializers import RetrieveCompanySerializer

from .models import AddOn, Invoice, PaymentMethod, Plan, ProcessedWebhookEvent, Subscription, SubscriptionAddOn
from .permissions import IsCompanyAdminForSubscription
from .serializers import (
    AddOnSerializer,
    InvoiceSerializer,
    PaymentMethodSerializer,
    PlanSerializer,
    SubscriptionAddOnSerializer,
    SubscriptionSerializer,
)

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)

# Ceiling on a single add-on purchase. Guards a BILLING endpoint against a typo or a crafted
# request; beyond this the answer is the Operation tier, not fifty Extra Farm line items.
MAX_ADDON_QUANTITY_PER_REQUEST = 20


def stripe_ts(ts):
    """Convert a Stripe unix timestamp to a timezone-aware datetime."""
    return dt.fromtimestamp(ts, tz=dt_timezone.utc) if ts else None


def internal_plans():
    """Plans that exist for staff provisioning and must never be self-serve selectable.

    `pilot` is free with unlimited farms, parcels and productions. It is granted deliberately by
    `provision_pilot` during white-glove onboarding; it is not something a visitor may choose.

    NOTE the shape. The obvious `.exclude(features__is_pilot=True)` is WRONG on a JSONField: for
    every row that simply lacks the key the comparison is NULL, `NOT NULL` is not true, and the
    row is dropped — so that expression returns ZERO plans, not "all but pilot". Verified against
    the live table. Excluding by primary key keeps the missing-key rows.
    """
    return Plan.objects.filter(features__is_pilot=True)


def self_serve_plans(queryset=None):
    """Active plans a user is allowed to pick without a human in the loop."""
    queryset = Plan.objects.filter(is_active=True) if queryset is None else queryset
    return queryset.exclude(pk__in=internal_plans().values("pk"))


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for listing subscription plans"""

    queryset = Plan.objects.filter(is_active=True)
    serializer_class = PlanSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        from django.db.models import Q

        # AllowAny: this list is public, so an internal plan listed here is an offer to the world.
        queryset = self_serve_plans(super().get_queryset())
        interval = self.request.query_params.get("interval")

        # Filter by interval if provided, but always include free plans (Starter)
        if interval:
            queryset = queryset.filter(Q(interval=interval) | Q(price=0))

        return queryset


class AddOnViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for listing available add-ons"""

    queryset = AddOn.objects.filter(is_active=True)
    serializer_class = AddOnSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Get active add-ons - no caching since QuerySets aren't JSON serializable
        queryset = AddOn.objects.filter(is_active=True)
        logger.info(f"Retrieved {queryset.count()} active add-ons")
        return queryset


def _may_manage_billing_for(user, company):
    """True when `user` may spend or stop money on `company`'s behalf.

    The same rule `IsCompanyAdminForSubscription.has_object_permission` applies to the
    subscription endpoints, stated once here so the checkout endpoints — which resolve their
    company from the REQUEST BODY and therefore cannot use an object-level permission — cannot
    drift away from it.
    """
    from users.models import WorksIn

    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    if company is None:
        return False
    return WorksIn.objects.filter(user=user, company=company, role=WorksIn.COMPANY_ADMIN).exists()


class SubscriptionViewSet(viewsets.ModelViewSet):
    """API endpoint for managing subscriptions"""

    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        # Billing operations require Company Admin role **of the company being billed**.
        # `IsCompanyAdminForSubscription.has_object_permission` enforces the second half, and
        # every action below is `detail=True`, so DRF calls it from `get_object()`.
        #
        # ⚠️ `create_session` and `create_customer_portal_session` used to be listed here. They
        # are NOT actions on this viewset — they live on `CheckoutViewSet`, whose
        # `permission_classes` is `[IsAuthenticated]`. Naming them here configured nothing while
        # reading as though checkout was admin-gated. It was not; both now carry the check
        # themselves via `_may_manage_billing_for`.
        write_actions = [
            "cancel",
            "reactivate",
            "change_plan",
            "add_addon",
        ]
        if self.action in write_actions or self.action in ["create", "update", "partial_update", "destroy"]:
            return [permissions.IsAuthenticated(), IsCompanyAdminForSubscription()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        if user.is_staff and self.action == "list":
            return Subscription.objects.all()
        return Subscription.objects.filter(company__in=user.companies.all())

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        """Return all billing data for ONE company in a single request.

        SCOPED TO A COMPANY, DELIBERATELY.

        This used to be `Subscription.objects.filter(company__in=user.companies.all()).first()`
        — no ordering, no company. A user who belongs to more than one company got whichever
        row Postgres happened to return from the heap, and the subscription page rendered THAT
        company's plan, price, billing period and usage limits beside the ACTIVE company's
        counts. Measured 2026-08-19: a demo account in two companies showed "Corporate
        $149/Monthly, Farms 1/4, Parcels 3/16" (a retired tier held by an unrelated company)
        while every other surface correctly read Compliance. The meter's numerator came from
        one company and its denominator from another.

        `Company.subscription` is a OneToOne, so "which subscription" is entirely decided by
        "which company" — the caller should say. `company_id` reuses the parameter name every
        other action here already takes (start_trial, create_session; they read it from the
        body, this one from the query string because it is a GET), and it is validated against
        the caller's own companies so it cannot be used to read someone else's billing.

        Omitting it does NOT mean "all of them". The response still describes exactly one
        company — the one owning the newest subscription — because a plan from one company
        beside cards from every company is the same defect only half fixed: a billing tab
        listing a card that cannot pay the plan printed above it.
        """
        try:
            user = request.user

            # Resolve the ONE company this payload describes, before anything else is queried.
            company_id = request.query_params.get("company_id")
            if company_id:
                try:
                    company_pk = int(company_id)
                except (TypeError, ValueError):
                    # `Company.id` is an AutoField, so `filter(id="undefined")` raises
                    # ValueError from inside the ORM. Under the blanket `except` below that
                    # surfaced as a 500 plus an ERROR-level traceback for what is only a
                    # malformed query string — and `?company_id=undefined` is one JavaScript
                    # template literal away from happening for real.
                    return Response(
                        {"error": "company_id must be an integer"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                company = user.companies.filter(id=company_pk).first()
                if company is None:
                    # Not 403: whether the company exists is not this caller's business.
                    return Response(
                        {"error": "Company not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                # No company named. Still answer for exactly one — the newest subscription's —
                # rather than mixing one company's plan with every company's cards. Half-scoping
                # is the same defect: a billing tab listing a card that cannot pay the plan
                # above it. Falls back to a company with no subscription at all so a brand-new
                # account still gets its own (empty) billing page.
                newest = self.get_queryset().select_related("company").order_by("-id").first()
                company = newest.company if newest else user.companies.order_by("id").first()

            # `__in=[]` for a user who belongs to no company: an empty result, without
            # `company=None` quietly turning into `company_id IS NULL`.
            companies = [company] if company is not None else []

            # `-id` is the ordering the unscoped branch above depends on. Kept here too so the
            # queryset is deterministic on its own terms rather than by luck of the heap.
            subscriptions = (
                self.get_queryset()
                .filter(company__in=companies)
                .select_related("plan", "pending_plan", "company")
                .prefetch_related("addons__addon")
                .order_by("-id")
            )
            subscription = subscriptions.first()

            # Get available add-ons
            addons = AddOn.objects.filter(is_active=True)

            # Payment methods and invoices for the scoped company. Both ORDERED: an unordered
            # queryset is exactly what produced the bug this method now guards against, and a
            # card list that reshuffles between loads is the same class of surprise. Default
            # card first, then newest.
            payment_methods = PaymentMethod.objects.filter(company__in=companies).order_by(
                "-is_default", "-created_at", "-id"
            )
            invoices = Invoice.objects.filter(company__in=companies).order_by("-invoice_date", "-id")

            # Return all data in one response
            response_data = {
                "subscription": SubscriptionSerializer(subscription).data if subscription else None,
                "addons": AddOnSerializer(addons, many=True).data,
                "paymentMethods": PaymentMethodSerializer(payment_methods, many=True).data,
                "invoices": InvoiceSerializer(invoices, many=True).data,
            }

            return Response(response_data)
        except Exception as e:
            logger.error("Error in dashboard endpoint: %s", e, exc_info=True)
            return Response(
                {"error": "Error fetching dashboard data. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="start-trial")
    def start_trial(self, request):
        """Put a company on Starter — FREE FOREVER, no card, no Stripe, no clock.

        Named `start_trial` for URL compatibility only; there is no trial any more. Starter used
        to be created as `status="trialing"` with a 14-day `trial_end` that `expire_trials`
        canceled, which contradicted the October plan ("Starter free forever") and the COG Pro
        migration page's anti-lock-in promise. The free tier is bounded by its LIMITS — one
        production a year, 2 GB, 1000 scans a month — not by a countdown.
        """
        user = request.user
        company_id = request.data.get("company_id")

        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)

        # Check user belongs to company
        if not user.companies.filter(id=company.id).exists():
            return Response({"error": "Not authorized"}, status=status.HTTP_403_FORBIDDEN)

        # One subscription per company. Not because the free tier is rationed — Starter is free
        # forever and a company may sit on it indefinitely — but because `Company.subscription`
        # is one-to-one, and re-running this would silently replace a PAID Compliance
        # subscription with the free tier.
        if hasattr(company, "subscription") or Subscription.objects.filter(company=company).exists():
            return Response(
                {"error": "Company already has a subscription."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the Starter plan
        starter_plan = Plan.objects.filter(slug="starter", is_active=True).first()
        if not starter_plan:
            return Response(
                {"error": "Starter plan not available"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Create local-only subscription (no Stripe). Active with no end date — see the docstring.
        subscription = Subscription.objects.create(
            company=company,
            plan=starter_plan,
            status="active",
            current_period_start=timezone.now(),
            current_period_end=None,
            trial_end=None,
        )

        logger.info("Free-forever Starter plan started for company %s", company.id)

        return Response(
            {
                "status": "Trial started successfully",
                "subscription": SubscriptionSerializer(subscription).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _uncancellable_reason(subscription):
        """Why this subscription cannot be cancelled through self-serve, or None if it can.

        A PAYLOAD gate, not a second copy of the UI's render gate. `UnifiedSubscription` already
        hides the button for Starter and pilot, and a render gate proves nothing about what the
        endpoint accepts: a stale tab, a replayed request or a direct POST all reach this action
        with a company-admin cookie. That is the whole edit-lock-gating class — the control has
        to read the rule, and so does the endpoint.

        Nothing here is a refusal to let a customer leave. It is a refusal to run a CHARGE-ENDING
        flow against something that is not being charged, which would only ever produce a
        confusing state ("your subscription will cancel on -") on a plan that never bills.
        """
        plan = subscription.plan
        if plan is None:
            return "This subscription has no plan attached and cannot be cancelled here."

        features = plan.features or {}

        if plan.slug == "pilot" or features.get("is_pilot") is True:
            # Ending a pilot is a conversation, per the pilot agreement — not a button.
            return (
                "Pilot accounts are comped by agreement and are not billed, so there is nothing "
                "to cancel. Email support and we will close it out with you."
            )

        if plan.slug == STARTER_PLAN_SLUG or plan.price == 0:
            # Starter is free forever. There is no charge to stop, and running the flow anyway
            # used to stamp `cancel_at_period_end=True` on a row whose `current_period_end` is
            # None — which rendered as "Your subscription will cancel on -" beside a Reactivate
            # button, on the one plan whose entire selling point is that nothing is ever due.
            return (
                "Your plan is free — there is nothing to cancel and nothing will ever be "
                "charged. Your records stay in Trazo. To close the account entirely, contact "
                "support."
            )

        return None

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Schedule cancellation at the end of the paid period, and record why.

        Cancellation is a DOWNGRADE to Starter, not an account deletion — the company keeps
        every record, keeps logging, and keeps the free tier forever. What actually stops is the
        certifier OUTPUTS (`compliance_exports`). The move itself happens when Stripe reports the
        subscription gone; see `land_on_free_tier`.

        Reason capture is OPTIONAL and always will be. California's ARL (AB 2863, in force since
        2025-07-01) prohibits obstructing or delaying cancellation, and a required question in
        the middle of a cancel flow is obstruction whatever it is labelled. A blank reason is a
        valid answer that must not cost the customer a second click.
        """
        subscription = self.get_object()

        blocked = self._uncancellable_reason(subscription)
        if blocked:
            return Response(
                {"error": blocked, "code": "not_cancellable"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validated against the model's own choices so a typo cannot silently create a bucket
        # that no report will ever count. An UNKNOWN reason is dropped rather than rejected —
        # the cancellation is what the customer asked for and must not fail over telemetry.
        # `request.data` is whatever the client sent. A JSON array or a bare string parses to a
        # non-mapping, and `.get` on it raises AttributeError OUTSIDE the try below — a 500 on a
        # billing endpoint from a malformed body.
        payload = request.data if hasattr(request.data, "get") else {}

        valid_reasons = {value for value, _ in Subscription.CANCELLATION_REASON_CHOICES}
        raw_reason = str(payload.get("reason") or "").strip()
        reason = raw_reason if raw_reason in valid_reasons else ""
        if raw_reason and not reason:
            logger.warning("Unrecognised cancellation reason %r from company %s", raw_reason, subscription.company_id)
        feedback = str(payload.get("feedback") or "").strip()[:2000]

        # Never overwrite an answer already given with silence.
        #
        # The UI swaps Cancel for Reactivate once `cancel_at_period_end` is set, so a second
        # cancel is a direct POST or a stale tab — and if it carried no reason it would blank the
        # one the customer actually gave. That is the only churn answer we will ever get from
        # them, and it is already snapshotted onto the SubscriptionEvent, so losing it here would
        # also make the row disagree with the log.
        if subscription.cancel_at_period_end:
            reason = reason or subscription.cancellation_reason
            feedback = feedback or subscription.cancellation_feedback

        try:
            if subscription.stripe_subscription_id:
                stripe.Subscription.modify(subscription.stripe_subscription_id, cancel_at_period_end=True)

            already_cancelling = subscription.cancel_at_period_end
            subscription.cancel_at_period_end = True
            subscription.cancellation_reason = reason
            subscription.cancellation_feedback = feedback
            # The moment they FIRST asked, kept. Re-stamping on a repeat request would move the
            # date the ARL acknowledgement is measured from.
            if not already_cancelling or subscription.cancellation_requested_at is None:
                subscription.cancellation_requested_at = timezone.now()
            subscription.save()

            _acknowledge_cancellation_request(subscription, request.user)

            return Response(
                {
                    "status": "subscription will be canceled at the end of the billing period",
                    "end_date": subscription.current_period_end,
                    # What the customer keeps, said by the server so the UI cannot drift from
                    # what `land_on_free_tier` actually does.
                    "downgrades_to": STARTER_PLAN_SLUG,
                }
            )
        except Exception as e:
            logger.error("Error canceling subscription: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to cancel subscription. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        """Reactivate a subscription that was scheduled for cancellation"""
        subscription = self.get_object()

        try:
            if subscription.stripe_subscription_id:
                stripe.Subscription.modify(subscription.stripe_subscription_id, cancel_at_period_end=False)

            subscription.cancel_at_period_end = False
            # Clear the churn answer along with the churn. Leaving it behind would attach the
            # reason a customer once gave to a subscription they decided to keep, and would then
            # be copied onto the NEXT cancellation event by `signals._cancellation_metadata`
            # even if that one was cancelled for something else entirely.
            subscription.cancellation_reason = ""
            subscription.cancellation_feedback = ""
            subscription.cancellation_requested_at = None
            subscription.save()

            return Response({"status": "subscription reactivated"})
        except Exception as e:
            logger.error("Error reactivating subscription: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to reactivate subscription. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _is_downgrade(self, current_plan, new_plan):
        """
        Determine if changing to new_plan is a downgrade.
        Upgrade-only policy: Users must contact support to downgrade.
        """
        plan_order = {
            "starter": 0,
            "basic": 1,
            "standard": 2,
            "corporate": 3,
            "enterprise": 4,
        }

        current_tier = 0
        new_tier = 0

        # Check slug for tier level (handles both monthly and yearly variants)
        for key, tier in plan_order.items():
            if key in current_plan.slug.lower():
                current_tier = tier
            if key in new_plan.slug.lower():
                new_tier = tier

        return new_tier < current_tier

    @action(detail=True, methods=["post"])
    def change_plan(self, request, pk=None):
        """Change subscription plan. Upgrades apply immediately with proration.
        Downgrades are scheduled for the end of the current billing period."""
        subscription = self.get_object()
        plan_id = request.data.get("plan_id")

        try:
            # self_serve_plans, not Plan.objects: hiding the pilot plan from the public list is
            # not a control if the id still works when posted here.
            plan = self_serve_plans().get(id=plan_id)
            is_downgrade = subscription.plan and self._is_downgrade(subscription.plan, plan)

            if subscription.stripe_subscription_id:
                stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
                item_id = stripe_sub["items"]["data"][0]["id"]

                if is_downgrade:
                    # Schedule downgrade at end of billing period
                    stripe.Subscription.modify(
                        subscription.stripe_subscription_id,
                        items=[{"id": item_id, "price": plan.stripe_price_id}],
                        proration_behavior="none",
                        billing_cycle_anchor="unchanged",
                    )
                    logger.info(
                        "Downgrade scheduled: Company %s from %s to %s at period end",
                        subscription.company_id,
                        subscription.plan.name,
                        plan.name,
                    )
                else:
                    # Upgrade immediately with proration
                    stripe.Subscription.modify(
                        subscription.stripe_subscription_id,
                        items=[{"id": item_id, "price": plan.stripe_price_id}],
                        proration_behavior="always_invoice",
                    )

            if is_downgrade:
                # Store pending plan - current plan features remain active until period end
                subscription.pending_plan = plan
                subscription.save(update_fields=["pending_plan", "updated_at"])
                message = "Plan will be downgraded at the end of your current billing period."
            else:
                # Upgrade immediately - apply new (higher) limits now
                subscription.plan = plan
                subscription.pending_plan = None
                subscription.save(update_fields=["plan", "pending_plan", "updated_at"])
                message = "Plan upgraded successfully."

            return Response(
                {
                    "status": message,
                    "is_downgrade": is_downgrade,
                    "pending_plan": PlanSerializer(plan).data if is_downgrade else None,
                    "subscription": SubscriptionSerializer(subscription).data,
                }
            )
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("Error changing plan: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to change plan. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def add_addon(self, request, pk=None):
        """Attach an add-on to the EXISTING subscription as a line item.

        Not a checkout session.
        ----------------------
        This used to call `stripe.checkout.Session.create(..., mode="subscription")`, which
        opens a SECOND Stripe subscription for the same company. One farm then had two
        subscriptions, two invoices and two renewal dates, and nothing in the product ever
        told the farmer which was which. Trazo sells one thing per farm — a yearly
        Compliance plan — and Extra Farm extends it; extending is a subscription ITEM, which
        is exactly the object Stripe provides for it.

        Adding an item also gets proration right for free: Stripe bills the remainder of the
        current period at the item's rate and folds the add-on into the SAME renewal from
        then on. A second subscription would have charged a full period immediately and then
        renewed on its own anniversary.
        """
        subscription = self.get_object()
        addon_id = request.data.get("addon_id")
        try:
            quantity = int(request.data.get("quantity", 1))
        except (TypeError, ValueError):
            return Response({"error": "quantity must be a whole number"}, status=status.HTTP_400_BAD_REQUEST)

        if not addon_id:
            return Response({"error": "addon_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        if quantity <= 0:
            return Response({"error": "quantity must be greater than 0"}, status=status.HTTP_400_BAD_REQUEST)

        # An upper bound, because this endpoint bills.
        #
        # There was none: a typo or a crafted request could send `quantity: 10000` and mint a
        # Stripe item for $1.49M in prorated charges. No real operation adds fifty farms in one
        # click, and the ones that would are an Operation-tier conversation anyway.
        if quantity > MAX_ADDON_QUANTITY_PER_REQUEST:
            return Response(
                {
                    "error": (
                        f"You can add up to {MAX_ADDON_QUANTITY_PER_REQUEST} at a time. "
                        "Contact support for a larger operation."
                    ),
                    "code": "ADDON_QUANTITY_TOO_LARGE",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            addon = AddOn.objects.get(id=addon_id, is_active=True)
        except AddOn.DoesNotExist:
            logger.error("Addon not found: %s", addon_id)
            return Response({"error": "Add-on not found"}, status=status.HTTP_404_NOT_FOUND)

        # An add-on with no verified Stripe price must not be sold.
        #
        # Migration 0016 NULLed `extra-establishment.stripe_price_id` because it still
        # pointed at a $30/MONTH price after 0014 repriced the add-on to $149/YEAR — a
        # Stripe Price is immutable, so repricing means minting a new one, and the row had
        # never been repointed. Refusing loudly here is the whole value of that NULL: the
        # alternative is handing Stripe an id that bills an amount the UI never showed.
        if not addon.stripe_price_id:
            logger.error("Add-on %s has no stripe_price_id; refusing to sell it", addon.slug)
            return Response(
                {
                    "error": (
                        "This add-on is not available for self-service purchase yet. "
                        "Contact support and we'll add it to your plan."
                    ),
                    "code": "ADDON_PRICE_UNAVAILABLE",
                },
                status=status.HTTP_409_CONFLICT,
            )

        if not subscription.stripe_subscription_id:
            return Response(
                {
                    "error": "An active billing subscription is required before adding an add-on.",
                    "code": "NO_STRIPE_SUBSCRIPTION",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "Attaching addon %s x%d to subscription %s (stripe %s)",
            addon.slug,
            quantity,
            subscription.id,
            subscription.stripe_subscription_id,
        )

        existing = SubscriptionAddOn.objects.filter(subscription=subscription, addon=addon).first()
        previous_quantity = existing.quantity if existing else 0

        # The quantity Stripe must END AT, computed once and used for BOTH sides.
        #
        # The create branch used to send `quantity=quantity` (the increment) while storing
        # `previous + quantity` locally. That only agreed when there was no existing row —
        # and a row with no `stripe_item_id` is exactly what the legacy webhook path and any
        # half-finished attempt leave behind. In that case a farm holding 3 extra farms who
        # bought 1 more was billed for 1 and granted 4.
        target_quantity = previous_quantity + quantity

        try:
            if existing and existing.stripe_item_id:
                # Already on the invoice — raise the quantity on the SAME item rather than
                # adding a second line for the same product.
                stripe.SubscriptionItem.modify(
                    existing.stripe_item_id,
                    quantity=target_quantity,
                    proration_behavior="create_prorations",
                )
                item_id = existing.stripe_item_id
                created_item = False
            else:
                item = stripe.SubscriptionItem.create(
                    subscription=subscription.stripe_subscription_id,
                    price=addon.stripe_price_id,
                    quantity=target_quantity,
                    proration_behavior="create_prorations",
                    metadata={
                        "company_id": str(subscription.company.id),
                        "addon_id": str(addon.id),
                        "addon_slug": addon.slug,
                    },
                )
                item_id = item.id
                created_item = True
        except Exception as e:
            # Nothing billed, nothing written. Safe to retry.
            logger.error("Stripe refused the add-on item: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to add the add-on. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                # Written HERE, not in a webhook. There is no checkout session to complete,
                # so `checkout.session.completed` never fires for this path — the entitlement
                # has to land in the same request that created the Stripe item, or the farmer
                # is billed for a farm they still cannot create.
                subscription_addon, _ = SubscriptionAddOn.objects.update_or_create(
                    subscription=subscription,
                    addon=addon,
                    defaults={"quantity": target_quantity, "stripe_item_id": item_id},
                )
        except Exception as e:
            # Billed but not entitled — the one outcome that must never survive a response.
            # Undo the Stripe side so the farmer is not charged for something they did not
            # get, and so a retry cannot stack a second item on the subscription.
            logger.error("Add-on entitlement write failed after billing; reverting Stripe: %s", e, exc_info=True)
            try:
                if created_item:
                    stripe.SubscriptionItem.delete(item_id)
                else:
                    stripe.SubscriptionItem.modify(
                        item_id, quantity=previous_quantity, proration_behavior="create_prorations"
                    )
            except Exception:
                # Both halves failed. Log loudly with everything needed to fix it by hand —
                # this is the case that has to reach a human, not a retry.
                logger.exception(
                    "MANUAL RECONCILIATION NEEDED: stripe item %s on subscription %s bills "
                    "quantity %d but no SubscriptionAddOn row was written",
                    item_id,
                    subscription.stripe_subscription_id,
                    target_quantity,
                )
            return Response(
                {"error": "Failed to add the add-on. Nothing was charged. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("Addon %s now at quantity %d on subscription %s", addon.slug, target_quantity, subscription.id)
        return Response(
            {
                # No `url`: nothing to redirect to. The client treats a missing url as
                # "applied immediately" and refetches, which is now the truth.
                "url": None,
                "addon": SubscriptionAddOnSerializer(subscription_addon).data,
                "prorated": True,
            }
        )


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for listing invoices"""

    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Invoice.objects.all().order_by("-invoice_date")
        return Invoice.objects.filter(company__in=user.companies.all()).order_by("-invoice_date")

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def download(self, request, pk=None):
        """
        Download invoice PDF from Stripe.
        Ensures user can only download invoices from their own companies.
        """
        try:
            # Get the invoice with security check
            invoice = self.get_object()

            # Additional security: ensure user has access to this invoice's company
            user = request.user
            if not user.is_staff and invoice.company not in user.companies.all():
                return Response(
                    {"detail": "You don't have permission to download this invoice."}, status=status.HTTP_403_FORBIDDEN
                )

            # Check if invoice has a PDF URL
            if not invoice.invoice_pdf:
                return Response({"detail": "Invoice PDF is not available."}, status=status.HTTP_404_NOT_FOUND)

            # Fetch the PDF from Stripe
            try:
                pdf_response = requests.get(invoice.invoice_pdf, timeout=30)
                pdf_response.raise_for_status()
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to download invoice PDF from Stripe: {e}")
                return Response(
                    {"detail": "Unable to retrieve invoice PDF from Stripe."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Create HTTP response with PDF content
            response = HttpResponse(pdf_response.content, content_type="application/pdf")

            # Set headers for file download
            invoice_filename = f"trazo-invoice-{invoice.stripe_invoice_id or invoice.id}.pdf"
            response["Content-Disposition"] = f'attachment; filename="{invoice_filename}"'
            response["Content-Length"] = len(pdf_response.content)

            # Add cache headers for better performance
            response["Cache-Control"] = "private, max-age=3600"  # Cache for 1 hour

            logger.info(f"Successfully served invoice download for invoice {invoice.id} to user {user.id}")
            return response

        except Invoice.DoesNotExist:
            return Response({"detail": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Unexpected error downloading invoice {pk}: {e}")
            return Response(
                {"detail": "An unexpected error occurred while downloading the invoice."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """API endpoint for managing payment methods"""

    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return PaymentMethod.objects.all()
        return PaymentMethod.objects.filter(company__in=user.companies.all())

    def perform_destroy(self, instance):
        """Delete payment method with Stripe detach and safety checks."""
        company = instance.company

        # Prevent deleting the default payment method
        if instance.is_default:
            from rest_framework.exceptions import ValidationError

            raise ValidationError("Cannot delete the default payment method. Set another card as default first.")

        # Prevent deleting the last payment method
        if company.payment_methods.count() <= 1:
            from rest_framework.exceptions import ValidationError

            raise ValidationError("Cannot delete the only payment method. Add another card first.")

        # Detach from Stripe first
        try:
            stripe.PaymentMethod.detach(instance.stripe_payment_method_id)
        except Exception as e:
            logger.warning("Error detaching payment method from Stripe: %s", e)

        instance.delete()

    @action(detail=True, methods=["post"])
    def set_default(self, request, pk=None):
        payment_method = self.get_object()
        company = payment_method.company

        with transaction.atomic():
            # Set all other payment methods as non-default
            company.payment_methods.update(is_default=False)

            # Set this payment method as default
            payment_method.is_default = True
            payment_method.save()

        # Update default payment method in Stripe if customer exists
        try:
            if hasattr(company, "subscription") and company.subscription.stripe_customer_id:
                stripe.Customer.modify(
                    company.subscription.stripe_customer_id,
                    invoice_settings={"default_payment_method": payment_method.stripe_payment_method_id},
                )
        except Exception as e:
            # Log the error but don't fail the request
            logger.warning("Error updating Stripe default payment method: %s", e)

        return Response({"status": "default payment method set"})


class PaymentThrottle(ScopedRateThrottle):
    """Throttle for payment-related endpoints."""

    scope = "api_sensitive"


# Create a dedicated ViewSet for checkout operations
class CheckoutViewSet(ViewSet):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    @action(detail=False, methods=["post"])
    def create_session(self, request):
        """Create a new Stripe checkout session"""
        data = request.data
        plan_id = data.get("plan_id")
        company_id = data.get("company_id")
        interval = data.get("interval", "monthly")
        new_company = data.get("new_company", False)
        trial_days = data.get("trial_days", 0)
        mode = data.get("mode", "subscription")  # Default to subscription mode

        # Add-on parameters
        addon_type = data.get("addon_type")
        quantity = int(data.get("quantity", 1))
        success_url = data.get("successUrl")
        cancel_url = data.get("cancelUrl")

        try:
            company = Company.objects.get(id=company_id)

            # ADMIN of this company, not merely a member of it (2026-08-22).
            #
            # This was `company in request.user.companies.all()` — bare membership, so any
            # Viewer or Farm Manager could start a charge on the company card or open the
            # Stripe Customer Portal (invoices, card swap, and depending on its Stripe
            # configuration a CANCEL that bypasses Trazo's own flow, its Starter/pilot gate and
            # its reason capture). `CheckoutViewSet.permission_classes` is `[IsAuthenticated]`
            # and the `SubscriptionViewSet.get_permissions` entry that appeared to cover these
            # two actions named actions that do not exist on that viewset, so nothing else was
            # standing behind this line.
            if not _may_manage_billing_for(request.user, company):
                return Response(
                    {"error": "Only Company Admins can manage billing for this company."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Create or get Stripe customer
            customer_id = None
            if hasattr(company, "subscription") and company.subscription.stripe_customer_id:
                customer_id = company.subscription.stripe_customer_id
            else:
                # Create a new customer
                customer = stripe.Customer.create(
                    email=request.user.email, name=company.name, metadata={"company_id": company.id}
                )
                customer_id = customer["id"]

                # Persist customer_id immediately to prevent orphaned Stripe customers
                if hasattr(company, "subscription"):
                    company.subscription.stripe_customer_id = customer_id
                    company.subscription.save(update_fields=["stripe_customer_id"])
                else:
                    starter_plan = Plan.objects.filter(slug="starter", is_active=True).first()
                    if starter_plan:
                        Subscription.objects.create(
                            company=company,
                            plan=starter_plan,
                            stripe_customer_id=customer_id,
                            status="incomplete",
                        )

            # Special mode for setting up a payment method without a charge
            if mode == "setup":
                # Determine success and cancel URLs
                success_url_final = (
                    success_url or f"{settings.FRONTEND_URL}/admin/dashboard/account/billing?success=true"
                )
                cancel_url_final = (
                    cancel_url or f"{settings.FRONTEND_URL}/admin/dashboard/account/billing?canceled=true"
                )

                # Create checkout session for payment method setup
                checkout_session = stripe.checkout.Session.create(
                    customer=customer_id,
                    payment_method_types=["card"],
                    mode="setup",
                    success_url=success_url_final,
                    cancel_url=cancel_url_final,
                    metadata={"company_id": company.id, "setup_type": "payment_method"},
                )

                return Response({"url": checkout_session.url})

            # For add-on purchases, we use a different flow
            if addon_type:
                # Add-ons are no longer sold through a checkout session.
                #
                # This branch opened a SECOND Stripe subscription for the same company
                # (`mode="subscription"` with the add-on as the only line item), duplicating
                # `SubscriptionViewSet.add_addon` — which now attaches the add-on to the
                # EXISTING subscription as an item, so it prorates correctly and renews on the
                # one date the farmer already knows. Two code paths that bill differently for
                # the same purchase is worse than either of them.
                #
                # Its slug map also offered `extraProduction`, `extraParcel` and `extraStorage`,
                # all deactivated by migrations 0006/0010 — a menu of things that cannot be
                # bought, kept alive only by a dictionary nobody re-read.
                return Response(
                    {
                        "error": "Add-ons are added to your existing subscription, not bought separately.",
                        "code": "USE_ADD_ADDON_ENDPOINT",
                        "endpoint": "/subscriptions/{subscription_id}/add_addon/",
                    },
                    status=status.HTTP_410_GONE,
                )

            # Regular subscription flow. self_serve_plans keeps the free unlimited pilot plan out
            # of checkout even if a caller supplies its id directly.
            plan = self_serve_plans().get(id=plan_id, interval=interval)

            # Set up trial parameters if requested
            subscription_data = {}
            if trial_days > 0:
                subscription_data["trial_period_days"] = trial_days

            # Determine success and cancel URLs based on whether this is a new company
            success_url = f"{settings.FRONTEND_URL}/admin/dashboard/stripe-success?success=true&session_id={{CHECKOUT_SESSION_ID}}"
            cancel_url = f"{settings.FRONTEND_URL}/pricing?canceled=true"

            if new_company:
                # If this is a new company, include redirect to establishment creation after successful subscription
                success_url += f"&new_company=true&company_id={str(company.id)}"
                cancel_url += f"&company_id={str(company.id)}&new_company=true"
            else:
                # Always include company_id for consistent handling
                success_url += f"&company_id={str(company.id)}"

            # Create checkout session
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": plan.stripe_price_id,
                        "quantity": 1,
                    }
                ],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                subscription_data=subscription_data,  # Include trial parameters
                metadata={
                    "company_id": company.id,
                    "plan_id": plan.id,
                    "interval": interval,
                    "new_company": str(new_company).lower(),
                    "trial_days": str(trial_days),
                },
            )

            return Response({"sessionId": checkout_session["id"]})
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found"}, status=status.HTTP_404_NOT_FOUND)
        except Company.DoesNotExist:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("Error creating checkout session: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to create checkout session. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"])
    def create_customer_portal_session(self, request):
        """Create a Stripe Customer Portal session for managing payment methods and billing"""
        data = request.data
        company_id = data.get("company_id")
        return_url = data.get("return_url", f"{settings.FRONTEND_URL}/admin/dashboard/account/billing")

        try:
            company = Company.objects.get(id=company_id)

            # ADMIN of this company, not merely a member of it (2026-08-22).
            #
            # This was `company in request.user.companies.all()` — bare membership, so any
            # Viewer or Farm Manager could start a charge on the company card or open the
            # Stripe Customer Portal (invoices, card swap, and depending on its Stripe
            # configuration a CANCEL that bypasses Trazo's own flow, its Starter/pilot gate and
            # its reason capture). `CheckoutViewSet.permission_classes` is `[IsAuthenticated]`
            # and the `SubscriptionViewSet.get_permissions` entry that appeared to cover these
            # two actions named actions that do not exist on that viewset, so nothing else was
            # standing behind this line.
            if not _may_manage_billing_for(request.user, company):
                return Response(
                    {"error": "Only Company Admins can manage billing for this company."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Check if company has a Stripe customer
            if not hasattr(company, "subscription") or not company.subscription.stripe_customer_id:
                return Response(
                    {"error": "Company does not have a Stripe customer account"}, status=status.HTTP_400_BAD_REQUEST
                )

            customer_id = company.subscription.stripe_customer_id

            # Create a portal session
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
                flow_data={
                    "type": "payment_method_update",
                },
            )

            # Return the URL to redirect the user to
            return Response({"url": portal_session.url})

        except Company.DoesNotExist:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("Error creating customer portal session: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to open billing portal. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"])
    def complete_checkout(self, request):
        """Complete the checkout after a successful payment"""
        session_id = request.data.get("session_id")

        logger.info("Complete checkout called with session_id=%s", session_id)

        if not session_id:
            return Response(
                {"success": False, "error": "Missing required parameters"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Retrieve checkout session from Stripe
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                logger.info("Retrieved Stripe session: %s", session_id)
            except stripe.error.StripeError as e:
                logger.error("Stripe error retrieving session: %s", e)
                return Response(
                    {"success": False, "error": "Payment processing error. Please try again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Read company_id from Stripe session metadata (NOT from client)
            session_metadata = session.get("metadata", {})
            company_id = session_metadata.get("company_id")

            if not company_id:
                logger.error("No company_id in session metadata for session %s", session_id)
                return Response(
                    {"success": False, "error": "Invalid checkout session"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Verify the requesting user has access to this company
            if not request.user.is_staff and not request.user.companies.filter(id=company_id).exists():
                logger.warning(
                    "User %s attempted complete_checkout for company %s without access",
                    request.user.id,
                    company_id,
                )
                return Response(
                    {"success": False, "error": "You do not have permission to manage this company"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Verify this is a valid checkout session
            # "paid" = normal payment, "no_payment_required" = trial or $0 checkout
            if session.get("payment_status") not in ("paid", "no_payment_required"):
                logger.warning(
                    "Payment not completed for session %s, status: %s",
                    session_id,
                    session.get("payment_status"),
                )
                return Response(
                    {"success": False, "error": "Payment not completed"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if this is an add-on purchase (one-time payment, not subscription)
            is_addon_purchase = session_metadata.get("is_addon_purchase") == "true"

            if is_addon_purchase:
                logger.info("Add-on purchase detected for session %s", session_id)

                try:
                    company = Company.objects.get(id=company_id)
                except Company.DoesNotExist:
                    logger.error("Company with ID %s not found for add-on purchase", company_id)
                    return Response(
                        {"success": False, "error": "Company not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Return success with company data
                try:
                    company_data = RetrieveCompanySerializer(company, context={"request": request}).data
                except Exception as serializer_error:
                    logger.warning(f"Error serializing company for add-on: {serializer_error}")
                    company_data = {
                        "id": company.id,
                        "name": company.name,
                        "has_subscription": True,
                    }

                logger.info(f"Add-on purchase completed successfully for company {company_id}")
                return Response(
                    {
                        "success": True,
                        "message": "Add-on purchase completed",
                        "company": company_data,
                        "is_addon": True,
                    }
                )

            # Get subscription ID from session (for regular subscription checkouts)
            subscription_id = session.get("subscription")
            if not subscription_id:
                logger.warning(f"No subscription found in session {session_id}")
                return Response(
                    {"success": False, "error": "No subscription found in this session"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get subscription details
            try:
                stripe_sub = stripe.Subscription.retrieve(subscription_id)
                logger.info("Retrieved Stripe subscription: %s", subscription_id)
            except stripe.error.StripeError as e:
                logger.error("Stripe error retrieving subscription: %s", e)
                return Response(
                    {"success": False, "error": "Payment processing error. Please try again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get company (company_id already validated from session metadata above)
            try:
                company = Company.objects.get(id=company_id)
            except Company.DoesNotExist:
                logger.error("Company with ID %s not found", company_id)
                return Response(
                    {"success": False, "error": "Company not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Get plan from price ID
            price_id = stripe_sub["items"]["data"][0]["price"]["id"]
            try:
                plan = Plan.objects.get(stripe_price_id=price_id)
            except Plan.DoesNotExist:
                logger.error("Plan with stripe_price_id %s not found", price_id)
                return Response(
                    {"success": False, "error": "Selected plan is not available. Please contact support."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Create or update subscription record
            subscription, created = Subscription.objects.update_or_create(
                company=company,
                defaults={
                    "plan": plan,
                    "stripe_subscription_id": subscription_id,
                    "stripe_customer_id": session.get("customer"),
                    "status": stripe_sub["status"],
                    "current_period_start": stripe_ts(stripe_sub["current_period_start"]),
                    "current_period_end": stripe_ts(stripe_sub["current_period_end"]),
                    "cancel_at_period_end": stripe_sub["cancel_at_period_end"],
                    "trial_end": (stripe_ts(stripe_sub["trial_end"]) if stripe_sub.get("trial_end") else None),
                },
            )

            # After creating the subscription, try to return updated company data
            try:
                # Try with full context
                company_data = RetrieveCompanySerializer(company, context={"request": request}).data
            except Exception as serializer_error:
                # If that fails, create a minimal data structure with just the essential subscription info
                logger.warning(f"Error serializing company with request context: {serializer_error}")
                company_data = {
                    "id": company.id,
                    "name": company.name,
                    "has_subscription": True,
                    "subscription": {
                        "id": subscription.id,
                        "status": subscription.status,
                        "current_period_end": subscription.current_period_end,
                        "stripe_subscription_id": subscription.stripe_subscription_id,
                    },
                    "subscription_plan": {
                        "id": plan.id,
                        "name": plan.name,
                        "interval": plan.interval,
                        "features": plan.features,
                    },
                }

            logger.info(f"Successfully completed checkout for session {session_id}, subscription {subscription.id}")
            return Response(
                {
                    "success": True,
                    "subscription_id": subscription.id,
                    "company": company_data,  # Include the company data with subscription info
                }
            )

        except Exception as e:
            logger.error("Unexpected error completing checkout: %s", e, exc_info=True)
            return Response(
                {"success": False, "error": "An unexpected error occurred. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Stripe webhook handler
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    logger.info(f"Received webhook event")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {str(e)}")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {str(e)}")
        return HttpResponse(status=400)

    # Handle the event in a transaction
    event_type = event["type"]
    event_id = event["id"]
    data = event["data"]["object"]

    logger.info("Processing webhook event: %s (id: %s)", event_type, event_id)

    # Idempotency check: skip already-processed events
    if ProcessedWebhookEvent.objects.filter(stripe_event_id=event_id).exists():
        logger.info("Skipping already-processed event: %s", event_id)
        return HttpResponse(status=200)

    # Debug: Log metadata for checkout sessions
    if event_type == "checkout.session.completed":
        metadata = data.get("metadata", {})
        logger.debug("checkout.session.completed - mode: %s, metadata: %s", data.get("mode"), metadata)
        logger.debug(
            "is_addon_purchase: %s, addon_id: %s",
            metadata.get("is_addon_purchase"),
            metadata.get("addon_id"),
        )

    try:
        with transaction.atomic():
            if event_type == "checkout.session.completed":
                # Check if this is a payment method setup session
                if data.get("mode") == "setup" and data.get("metadata", {}).get("setup_type") == "payment_method":
                    logger.info("Checkout session completed for payment method setup")
                # Check if this is a blockchain verification subscription
                elif data.get("metadata", {}).get("subscription_type") == "blockchain_verification":
                    handle_blockchain_checkout_completed(data)
                # Check if this is an add-on purchase
                elif data.get("metadata", {}).get("is_addon_purchase") == "true":
                    handle_addon_purchase_completed(data)
                elif data.get("mode") == "payment" and data.get("metadata", {}).get("addon_id"):
                    handle_addon_purchase_completed(data)
                else:
                    handle_checkout_session_completed(data)
            elif event_type == "setup_intent.succeeded":
                handle_setup_intent_succeeded(data)
            elif event_type == "invoice.created":
                handle_invoice_created(data)
            elif event_type == "invoice.finalized":
                handle_invoice_finalized(data)
            elif event_type == "invoice.paid":
                handle_invoice_paid(data)
            elif event_type == "invoice.payment_succeeded":
                handle_invoice_payment_succeeded(data)
            elif event_type == "invoice.payment_failed":
                handle_invoice_payment_failed(data)
            elif event_type == "customer.subscription.created":
                # Check if this is a blockchain subscription
                if data.get("metadata", {}).get("subscription_type") == "blockchain_verification":
                    handle_blockchain_subscription_created(data)
                else:
                    handle_subscription_created(data)
            elif event_type == "customer.subscription.updated":
                handle_subscription_updated(data)
            elif event_type == "customer.subscription.deleted":
                handle_customer_subscription_deleted(data)
            elif event_type == "payment_method.attached":
                handle_payment_method_attached(data)
            else:
                logger.warning("Unhandled webhook event type: %s", event_type)

        # Record successful processing for idempotency
        ProcessedWebhookEvent.objects.create(
            stripe_event_id=event_id,
            event_type=event_type,
            success=True,
        )

        logger.info("Successfully processed webhook event: %s", event_type)
        return HttpResponse(status=200)

    except (Company.DoesNotExist, Plan.DoesNotExist, AddOn.DoesNotExist) as e:
        # Permanent failure — data doesn't exist, retrying won't help
        logger.error("Permanent webhook failure for %s: %s", event_type, e, exc_info=True)
        ProcessedWebhookEvent.objects.create(
            stripe_event_id=event_id,
            event_type=event_type,
            success=False,
            error_message=str(e),
        )
        return HttpResponse(status=200)
    except Exception as e:
        # Transient failure — Stripe will retry
        logger.error("Transient webhook failure for %s: %s", event_type, e, exc_info=True)
        return HttpResponse(status=500)


def handle_checkout_session_completed(session):
    """Process completed checkout session"""
    try:
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        company_id = session.get("metadata", {}).get("company_id")
        plan_id = session.get("metadata", {}).get("plan_id")

        if not customer_id or not subscription_id or not company_id or not plan_id:
            logger.warning("Missing required data in checkout session")
            return

        company = Company.objects.get(id=company_id)
        plan = Plan.objects.get(id=plan_id)

        # Retrieve subscription details from Stripe
        stripe_sub = stripe.Subscription.retrieve(subscription_id)

        with transaction.atomic():
            # Create or update subscription
            subscription, created = Subscription.objects.update_or_create(
                company=company,
                defaults={
                    "plan": plan,
                    "stripe_subscription_id": subscription_id,
                    "stripe_customer_id": customer_id,
                    "status": stripe_sub["status"],
                    "current_period_start": stripe_ts(stripe_sub["current_period_start"]),
                    "current_period_end": stripe_ts(stripe_sub["current_period_end"]),
                    "cancel_at_period_end": stripe_sub["cancel_at_period_end"],
                    "trial_end": (stripe_ts(stripe_sub["trial_end"]) if stripe_sub.get("trial_end") else None),
                },
            )
    except Exception as e:
        logger.exception("Error in handle_checkout_session_completed: %s", e)
        raise


def handle_blockchain_checkout_completed(session):
    """Process completed blockchain verification checkout session"""
    try:
        metadata = session.get("metadata", {})
        company_id = metadata.get("company_id")

        if not company_id:
            logger.error("Missing company_id in blockchain checkout session metadata")
            return

        company = Company.objects.get(id=company_id)
        company.blockchain_subscription_status = True
        company.save()

        logger.info(f"Blockchain subscription activated for company {company_id} via checkout.session.completed")
    except Company.DoesNotExist:
        logger.error(f"Company {company_id} not found for blockchain subscription")
        raise
    except Exception as e:
        logger.exception("Error in handle_blockchain_checkout_completed: %s", e)
        raise


def handle_blockchain_subscription_created(subscription_data):
    """Process blockchain verification subscription creation"""
    try:
        metadata = subscription_data.get("metadata", {})
        company_id = metadata.get("company_id")

        if not company_id:
            logger.error("Missing company_id in blockchain subscription metadata")
            return

        company = Company.objects.get(id=company_id)
        company.blockchain_subscription_status = True
        company.save()

        logger.info(f"Blockchain subscription activated for company {company_id} via customer.subscription.created")
    except Company.DoesNotExist:
        logger.error(f"Company {company_id} not found for blockchain subscription")
        raise
    except Exception as e:
        logger.exception("Error in handle_blockchain_subscription_created: %s", e)
        raise


def handle_invoice_payment_succeeded(invoice):
    """Process successful invoice payment"""
    try:
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        # Get subscription from our database
        subscription = Subscription.objects.filter(stripe_subscription_id=subscription_id).first()
        if not subscription:
            return

        # Create or update invoice record
        Invoice.objects.update_or_create(
            stripe_invoice_id=invoice["id"],
            defaults={
                "company": subscription.company,
                "subscription": subscription,
                "number": invoice.get("number", ""),
                "amount": invoice["amount_paid"] / 100,  # Convert from cents
                "status": "paid",
                "invoice_date": stripe_ts(invoice["created"]),
                "due_date": stripe_ts(invoice["due_date"]) if invoice.get("due_date") else None,
                "invoice_pdf": invoice.get("invoice_pdf"),
            },
        )

        # Update subscription status if needed
        if subscription.status != "active" and invoice["paid"]:
            subscription.status = "active"
            subscription.save()

    except Exception as e:
        logger.exception("Error in handle_invoice_payment_succeeded: %s", e)
        raise


def handle_invoice_payment_failed(invoice):
    """Process failed invoice payment"""
    try:
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        # Get subscription from our database
        subscription = Subscription.objects.filter(stripe_subscription_id=subscription_id).first()
        if not subscription:
            return

        # Create or update invoice record
        Invoice.objects.update_or_create(
            stripe_invoice_id=invoice["id"],
            defaults={
                "company": subscription.company,
                "subscription": subscription,
                "number": invoice.get("number", ""),
                "amount": invoice["amount_due"] / 100,  # Convert from cents
                "status": "uncollectible" if invoice.get("uncollectible") else "open",
                "invoice_date": stripe_ts(invoice["created"]),
                "due_date": stripe_ts(invoice["due_date"]) if invoice.get("due_date") else None,
                "invoice_pdf": invoice.get("invoice_pdf"),
            },
        )

        # Update subscription status.
        #
        # `past_due` is NOT a lockout (see `company.models.PAID_PLAN_STATUSES`): the plan stays
        # live for the whole of Stripe's retry window, because a declined card is a billing
        # problem and answering it by cutting a farm off from its own harvest records in the
        # middle of a season is not a remedy. What it does trigger is a notice, so the customer
        # can fix the card before Stripe gives up and the subscription really does end.
        if subscription.status == "active":
            subscription.status = "past_due"
            subscription.save()
            _notify_payment_failed(subscription, invoice)

    except Exception as e:
        logger.exception("Error in handle_invoice_payment_failed: %s", e)
        raise


def _notify_payment_failed(subscription, invoice):
    """Tell the customer their card was declined and that nothing has been switched off.

    Never raises: a mail failure must not make the webhook 500, because Stripe would then retry
    the whole handler and the subscription state has already been written.
    """
    try:
        from subscriptions.utils import resolve_billing_recipient, send_payment_failed_email

        email, first_name = resolve_billing_recipient(subscription.company)
        if not email:
            logger.warning(
                "No billing contact for company %s — payment-failed notice not sent.",
                subscription.company_id,
            )
            return

        amount_due = invoice.get("amount_due")
        send_payment_failed_email(
            email=email,
            username=first_name,
            company_name=subscription.company.name,
            plan_name=subscription.plan.name if subscription.plan else "",
            amount_due=(amount_due / 100) if amount_due else None,
        )
    except Exception:
        logger.exception(
            "Failed to send payment-failed notice for company %s",
            getattr(subscription, "company_id", None),
        )


def handle_invoice_created(invoice_data):
    """Process invoice creation"""
    try:
        subscription_id = invoice_data.get("subscription")
        logger.info(f"Processing invoice.created for subscription_id: {subscription_id}")

        if not subscription_id:
            logger.warning("No subscription_id in invoice data")
            return

        # Find subscription with this Stripe subscription ID
        subscription = Subscription.objects.filter(stripe_subscription_id=subscription_id).first()
        if not subscription:
            # Fallback: find by customer ID (handles race condition where
            # customer.subscription.created webhook hasn't been processed yet)
            customer_id = invoice_data.get("customer")
            if customer_id:
                subscription = Subscription.objects.filter(stripe_customer_id=customer_id).first()
                if subscription and not subscription.stripe_subscription_id:
                    # Backfill the stripe_subscription_id
                    subscription.stripe_subscription_id = subscription_id
                    subscription.save(update_fields=["stripe_subscription_id", "updated_at"])
                    logger.info(
                        "Backfilled stripe_subscription_id=%s on subscription %s via customer %s",
                        subscription_id,
                        subscription.id,
                        customer_id,
                    )
        if not subscription:
            logger.warning(
                "No subscription found for stripe_subscription_id=%s or customer — "
                "the invoice.created webhook arrived before the subscription was recorded locally.",
                subscription_id,
            )
            return

        # Create or update invoice record
        Invoice.objects.update_or_create(
            stripe_invoice_id=invoice_data["id"],
            defaults={
                "company": subscription.company,
                "subscription": subscription,
                "number": invoice_data.get("number", ""),
                "amount": invoice_data["total"] / 100,  # Convert from cents
                "status": "draft",
                "invoice_date": stripe_ts(invoice_data["created"]),
                "due_date": (stripe_ts(invoice_data["due_date"]) if invoice_data.get("due_date") else None),
                "invoice_pdf": invoice_data.get("invoice_pdf", ""),
            },
        )
        logger.info(f"Invoice created: {invoice_data['id']} for subscription {subscription_id}")

    except Exception as e:
        logger.exception("Error in handle_invoice_created: %s", e)
        raise


def handle_invoice_finalized(invoice_data):
    """Process invoice finalization — PDF URL becomes available at this stage"""
    try:
        invoice = Invoice.objects.filter(stripe_invoice_id=invoice_data["id"]).first()
        if invoice:
            invoice.status = "open"
            # PDF URL and number become available when invoice is finalized
            if invoice_data.get("invoice_pdf"):
                invoice.invoice_pdf = invoice_data["invoice_pdf"]
            if invoice_data.get("number"):
                invoice.number = invoice_data["number"]
            invoice.save()
            logger.info(f"Invoice finalized: {invoice_data['id']}")
        else:
            logger.warning(f"Invoice not found for finalization: {invoice_data['id']}")

    except Exception as e:
        logger.exception("Error in handle_invoice_finalized: %s", e)
        raise


def handle_invoice_paid(invoice_data):
    """Process invoice payment"""
    try:
        invoice = Invoice.objects.filter(stripe_invoice_id=invoice_data["id"]).first()
        if invoice:
            invoice.status = "paid"
            # Capture PDF URL and invoice number if available
            if invoice_data.get("invoice_pdf"):
                invoice.invoice_pdf = invoice_data["invoice_pdf"]
            if invoice_data.get("number") and not invoice.number:
                invoice.number = invoice_data["number"]
            invoice.save()
            logger.info(f"Invoice paid: {invoice_data['id']}")
        else:
            # Invoice record doesn't exist yet — create it (handles webhook ordering race)
            subscription_id = invoice_data.get("subscription")
            customer_id = invoice_data.get("customer")
            subscription = None
            if subscription_id:
                subscription = Subscription.objects.filter(stripe_subscription_id=subscription_id).first()
            if not subscription and customer_id:
                subscription = Subscription.objects.filter(stripe_customer_id=customer_id).first()

            if subscription:
                Invoice.objects.create(
                    stripe_invoice_id=invoice_data["id"],
                    company=subscription.company,
                    subscription=subscription,
                    number=invoice_data.get("number", ""),
                    amount=invoice_data.get("total", 0) / 100,
                    status="paid",
                    invoice_date=stripe_ts(invoice_data.get("created")),
                    due_date=stripe_ts(invoice_data.get("due_date")) if invoice_data.get("due_date") else None,
                    invoice_pdf=invoice_data.get("invoice_pdf", ""),
                )
                logger.info(f"Invoice created and marked paid: {invoice_data['id']}")
            else:
                logger.warning(f"Invoice not found and no subscription for payment: {invoice_data['id']}")

    except Exception as e:
        logger.exception("Error in handle_invoice_paid: %s", e)
        raise


def handle_subscription_updated(subscription_data):
    """Process subscription update. Applies pending downgrades when billing period changes."""
    try:
        subscription = Subscription.objects.filter(stripe_subscription_id=subscription_data["id"]).first()

        if not subscription:
            return

        # Detect billing period change (new period_start means renewal happened)
        new_period_start = stripe_ts(subscription_data["current_period_start"])
        period_changed = (
            subscription.current_period_start is None or new_period_start > subscription.current_period_start
        )

        # Update subscription details
        subscription.status = subscription_data["status"]
        subscription.current_period_start = new_period_start
        subscription.current_period_end = stripe_ts(subscription_data["current_period_end"])
        subscription.cancel_at_period_end = subscription_data["cancel_at_period_end"]

        if subscription_data.get("trial_end"):
            subscription.trial_end = stripe_ts(subscription_data["trial_end"])

        # Apply pending downgrade when billing period renews
        if period_changed and subscription.pending_plan:
            logger.info(
                "Applying pending downgrade for company %s: %s -> %s",
                subscription.company_id,
                subscription.plan.name,
                subscription.pending_plan.name,
            )
            subscription.plan = subscription.pending_plan
            subscription.pending_plan = None

        subscription.save()

    except Exception as e:
        logger.exception("Error in handle_subscription_updated: %s", e)
        raise


def handle_customer_subscription_deleted(subscription_data):
    """Process subscription cancellation"""
    try:
        # Check if this is a blockchain verification subscription
        metadata = subscription_data.get("metadata", {})
        if metadata.get("subscription_type") == "blockchain_verification":
            company_id = metadata.get("company_id")
            if company_id:
                try:
                    company = Company.objects.get(id=company_id)
                    company.blockchain_subscription_status = False
                    company.save()
                    logger.info("Blockchain subscription cancelled for company %s", company_id)
                except Company.DoesNotExist:
                    logger.error("Company %s not found for blockchain cancellation", company_id)
            return

        subscription = Subscription.objects.filter(stripe_subscription_id=subscription_data["id"]).first()

        if not subscription:
            return

        land_on_free_tier(subscription)

    except Exception as e:
        logger.exception("Error in handle_customer_subscription_deleted: %s", e)
        raise


def land_on_free_tier(subscription):
    """End a paid subscription by MOVING IT TO STARTER — never by locking the company out.

    THE ONE PLACE a paid subscription is wound down. Called when Stripe reports the
    subscription gone (`customer.subscription.deleted`), which happens both when the customer
    cancelled at period end and when collection was finally abandoned.

    It used to be `subscription.status = "canceled"; subscription.save()`. That looks harmless
    and is not: `Company.subscription_plan` resolved for no status but active/trialing, so the
    row went to None and took everything with it — no parcels, no productions, no photo or
    document upload, no voice, and 403 on all seven compliance-export doors. A farm that paid
    $249 and simply did not renew ended up locked out of records it is required by
    §205.103(b)(4) to keep for five years, and strictly worse off than someone signing up that
    morning for free. `Company.subscription_plan` now ALSO falls back to Starter on its own, so
    the lockout cannot come back by a path that forgets to call this; the two are deliberate
    belt and braces. This one makes the DATA right — the billing page reads Starter, the event
    log books the churn, MRR drops to zero — and the resolver makes the SYSTEM safe when a
    webhook is missed, delayed or replayed.

    Stripe ids: `stripe_subscription_id` is CLEARED because that subscription no longer exists
    in Stripe and any later `Subscription.modify` against it would 404. `stripe_customer_id` is
    KEPT — the customer does still exist, still owns the payment methods and the invoice
    history, and is what a win-back checkout or a billing-portal visit needs.
    """
    previous_plan = subscription.plan
    starter_plan = Plan.objects.filter(slug=STARTER_PLAN_SLUG, is_active=True).first()

    if not starter_plan:
        # `create_plans` is the only thing that creates plan rows, so this means a broken
        # install rather than a customer state. Loud, because the alternative is silently
        # leaving the farm on a plan Stripe is no longer billing.
        logger.error(
            "Starter plan missing — cannot land company %s on the free tier after cancellation.",
            subscription.company_id,
        )
        return

    subscription.plan = starter_plan
    subscription.status = "active"
    subscription.pending_plan = None
    subscription.cancel_at_period_end = False
    subscription.stripe_subscription_id = None
    # Starter does not renew and does not lapse, so it carries no period end — the same shape
    # `company.views.CompanyViewSet.create` gives a brand-new company. Leaving the old paid
    # period end in place would print a "Next billing date" for a plan that never bills.
    subscription.current_period_start = timezone.now()
    subscription.current_period_end = None
    subscription.trial_end = None
    subscription.save()

    logger.info(
        "Company %s moved from %s to Starter after cancellation.",
        subscription.company_id,
        previous_plan.slug if previous_plan else "unknown",
    )

    _notify_subscription_canceled(subscription, previous_plan)


def _acknowledge_cancellation_request(subscription, user):
    """Send the ARL acknowledgement for a cancellation REQUEST.

    Separate from `_notify_subscription_canceled`, which fires weeks later when Stripe reports
    the subscription actually gone. Both are needed and they say different things: this one
    confirms the request, names the date the paid features stop, and shows how to undo it while
    the subscription is still live; the other confirms the move to Starter has happened.

    Addressed to the person who clicked, not to `company_admins.first()`. They are a company
    admin by permission class, they are the one owed the acknowledgement, and on a farm with
    several admins the arbitrary "first" is frequently not them.

    Never raises. A failed send must not roll back a cancellation the customer already
    confirmed and that Stripe has already accepted — that would leave the two systems
    disagreeing about whether the customer is still a customer.
    """
    try:
        recipient = getattr(user, "email", None)
        if not recipient:
            logger.warning(
                "No email for user %s — cancellation acknowledgement not sent for company %s.",
                getattr(user, "id", None),
                subscription.company_id,
            )
            return

        from subscriptions.utils import send_cancellation_scheduled_email

        send_cancellation_scheduled_email(
            email=recipient,
            username=getattr(user, "first_name", "") or "",
            company_name=subscription.company.name,
            plan_name=subscription.plan.name if subscription.plan else "",
            end_date=subscription.current_period_end,
        )
    except Exception:
        logger.exception(
            "Failed to send cancellation acknowledgement for company %s",
            getattr(subscription, "company_id", None),
        )


def _notify_subscription_canceled(subscription, previous_plan):
    """Send the post-cancellation acknowledgement.

    Swallows failures — a webhook must not 500 and be retried forever because SendGrid was
    down — but logs them at ERROR with a stack trace. The previous version swallowed a
    `TemplateDoesNotExist` here for months: `subscriptions/utils.py` rendered a
    `subscription_emails/` namespace that has never existed in this repo, so the acknowledgement
    California's ARL requires after a cancellation was never sent to anyone, and nothing said so
    above DEBUG.
    """
    try:
        company = subscription.company

        from subscriptions.utils import resolve_billing_recipient, send_subscription_canceled_email

        email, first_name = resolve_billing_recipient(company)
        if not email:
            logger.warning(
                "No billing contact for company %s — cancellation confirmation not sent.",
                company.id,
            )
            return

        send_subscription_canceled_email(
            email=email,
            username=first_name,
            company_name=company.name,
            previous_plan_name=previous_plan.name if previous_plan else "",
        )
    except Exception:
        logger.exception(
            "Failed to send cancellation acknowledgement for company %s",
            getattr(subscription, "company_id", None),
        )


def handle_payment_method_attached(payment_method_data):
    """Process payment method attachment"""
    try:
        customer_id = payment_method_data.get("customer")
        if not customer_id:
            return

        # Find the subscription with this customer ID
        subscription = Subscription.objects.filter(stripe_customer_id=customer_id).first()
        if not subscription:
            return

        company = subscription.company

        # Get card details
        card = payment_method_data.get("card", {})
        if not card:
            return

        # Create payment method record atomically to prevent duplicates
        with transaction.atomic():
            payment_method, created = PaymentMethod.objects.get_or_create(
                stripe_payment_method_id=payment_method_data["id"],
                defaults={
                    "company": company,
                    "card_brand": card.get("brand", "").lower(),
                    "last_4": card.get("last4", ""),
                    "exp_month": card.get("exp_month", 0),
                    "exp_year": card.get("exp_year", 0),
                    "is_default": False,
                },
            )

            if created:
                # Set as default if it's the first payment method
                is_first = company.payment_methods.count() == 1
                if is_first:
                    payment_method.is_default = True
                    payment_method.save(update_fields=["is_default"])
                    stripe.Customer.modify(
                        customer_id,
                        invoice_settings={"default_payment_method": payment_method_data["id"]},
                    )

    except Exception as e:
        logger.exception("Error in handle_payment_method_attached: %s", e)
        raise


def handle_subscription_created(subscription_data):
    """Process newly created subscription"""
    try:
        # Get company_id from metadata
        company_id = subscription_data.get("metadata", {}).get("company_id")
        if not company_id:
            # Try to get it from the customer's metadata
            customer_id = subscription_data.get("customer")
            if customer_id:
                customer = stripe.Customer.retrieve(customer_id)
                company_id = customer.get("metadata", {}).get("company_id")

        if not company_id:
            logger.warning(
                "Cannot find company_id in subscription metadata for subscription %s", subscription_data.get("id")
            )
            return

        company = Company.objects.get(id=company_id)

        # Get plan from Stripe price ID
        items_data = subscription_data.get("items", {}).get("data", [])
        if not items_data:
            logger.warning("No items in subscription %s", subscription_data.get("id"))
            return

        price_id = items_data[0].get("price", {}).get("id")
        plan = Plan.objects.filter(stripe_price_id=price_id).first()

        # Build defaults — only set plan if we found a matching one
        defaults = {
            "stripe_subscription_id": subscription_data.get("id"),
            "stripe_customer_id": subscription_data.get("customer"),
            "status": subscription_data.get("status", "active"),
            "cancel_at_period_end": subscription_data.get("cancel_at_period_end", False),
            "trial_end": (
                stripe_ts(subscription_data.get("trial_end")) if subscription_data.get("trial_end") else None
            ),
        }
        if plan:
            defaults["plan"] = plan

        # Only set period fields if present in the data
        if subscription_data.get("current_period_start"):
            defaults["current_period_start"] = stripe_ts(subscription_data["current_period_start"])
        if subscription_data.get("current_period_end"):
            defaults["current_period_end"] = stripe_ts(subscription_data["current_period_end"])

        # Create or update subscription
        subscription, created = Subscription.objects.update_or_create(
            company=company,
            defaults=defaults,
        )

        logger.info(
            "Subscription %s for company %s (stripe_sub_id: %s)",
            "created" if created else "updated",
            company.name,
            subscription_data["id"],
        )

    except Exception as e:
        logger.exception("Error in handle_subscription_created: %s", e)
        raise


def handle_addon_purchase_completed(session):
    """Process completed add-on purchase"""
    try:
        metadata = session.get("metadata", {})

        # Extract data from session metadata
        company_id = metadata.get("company_id")
        subscription_id = metadata.get("subscription_id")
        addon_id = metadata.get("addon_id")
        quantity = int(metadata.get("quantity", 1))
        addon_type = metadata.get("addon_type")
        return_url = metadata.get("return_url", None)

        # Log the addon purchase data
        logger.info(
            f"Processing add-on purchase: company={company_id}, addon={addon_id}, quantity={quantity}, type={addon_type}"
        )

        if not company_id or not addon_id:
            logger.error("Missing required data in add-on purchase metadata")
            return

        company = Company.objects.get(id=company_id)
        addon = AddOn.objects.get(id=addon_id)

        # Find the subscription - either by ID in metadata or from company
        if subscription_id:
            subscription = Subscription.objects.get(id=subscription_id, company=company)
        else:
            # Make sure the company has an active subscription
            if not hasattr(company, "subscription") or not company.subscription.stripe_subscription_id:
                logger.error(f"Company {company.id} has no active subscription for add-on purchase")
                return
            subscription = company.subscription

        with transaction.atomic():
            # Create subscription add-on record
            # Limits are computed dynamically by Company.can_create_* from
            # base plan features + SubscriptionAddOn quantities.
            subscription_addon, created = SubscriptionAddOn.objects.get_or_create(
                subscription=subscription, addon=addon, defaults={"quantity": quantity}
            )

            if not created:
                subscription_addon.quantity += quantity
                subscription_addon.save()
                logger.info("Updated existing addon quantity to %d", subscription_addon.quantity)
            else:
                logger.info("Created new addon %s with quantity %d", addon.name, quantity)

            # Create an invoice record for the add-on purchase
            # Use the Stripe invoice ID if available, otherwise use payment_intent
            # prefixed to distinguish from real invoice IDs
            stripe_invoice_id = session.get("invoice")
            if not stripe_invoice_id:
                payment_intent = session.get("payment_intent")
                stripe_invoice_id = f"addon_{payment_intent}" if payment_intent else None

            if stripe_invoice_id:
                Invoice.objects.get_or_create(
                    stripe_invoice_id=stripe_invoice_id,
                    defaults={
                        "company": company,
                        "subscription": subscription,
                        "number": f"ADDON-{addon.slug}-{quantity}",
                        "amount": addon.price * quantity,
                        "status": "paid",
                        "invoice_date": timezone.now(),
                    },
                )

            logger.info(f"Successfully processed add-on purchase: {addon.name} x{quantity} for {company.name}")
            return True
    except Exception as e:
        logger.exception("Error in handle_addon_purchase_completed: %s", e)
        raise


def handle_setup_intent_succeeded(setup_intent):
    """Process successful setup intent for payment methods"""
    try:
        # Get the payment method ID from the setup intent
        payment_method_id = setup_intent.get("payment_method")
        customer_id = setup_intent.get("customer")

        if not payment_method_id or not customer_id:
            logger.warning("Missing payment_method_id or customer_id in setup intent")
            return

        # Retrieve payment method details from Stripe
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

        # Find the subscription with this customer ID
        subscription = Subscription.objects.filter(stripe_customer_id=customer_id).first()
        if not subscription:
            logger.warning("No subscription found for customer %s", customer_id)
            return

        company = subscription.company

        # Get card details
        card = payment_method.get("card", {})
        if not card:
            logger.warning("No card details in payment method %s", payment_method_id)
            return

        # Use get_or_create to prevent IntegrityError when payment_method.attached
        # webhook also fires for the same payment method
        with transaction.atomic():
            payment_method_obj, created = PaymentMethod.objects.get_or_create(
                stripe_payment_method_id=payment_method_id,
                defaults={
                    "company": company,
                    "card_brand": card.get("brand", "").lower(),
                    "last_4": card.get("last4", ""),
                    "exp_month": card.get("exp_month", 0),
                    "exp_year": card.get("exp_year", 0),
                    "is_default": False,
                },
            )

            if created:
                # Set as default if it's the first payment method
                is_first = company.payment_methods.count() == 1
                if is_first:
                    payment_method_obj.is_default = True
                    payment_method_obj.save(update_fields=["is_default"])
                    stripe.Customer.modify(
                        customer_id,
                        invoice_settings={"default_payment_method": payment_method_id},
                    )

        logger.info(
            "Payment method %s %s for company %s",
            payment_method_id,
            "created" if created else "already exists",
            company.name,
        )

    except Exception as e:
        logger.exception("Error in handle_setup_intent_succeeded: %s", e)
        raise


class BlockchainSubscriptionView(APIView):
    """API endpoints for blockchain subscription management"""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentThrottle]

    def post(self, request):
        """
        Create Stripe checkout session for blockchain verification subscription
        POST /api/billing/subscribe-blockchain/
        """
        try:
            # The blockchain add-on was WITHDRAWN on 2026-08-03 and the feature disabled on
            # 2026-08-06 (`BLOCKCHAIN_ENABLED` defaults False).
            #
            # This endpoint previously stayed reachable and was safe only because the AddOn row
            # carried `is_active=False` — i.e. a DATA flag was the sole thing standing between a
            # customer and a live $15/mo charge for a product Trazo does not sell. One reseed or
            # one admin toggle would have re-opened it. Gate on the SETTING as well, so turning the
            # product back on is a deliberate act rather than an accident.
            from django.conf import settings

            if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
                return Response(
                    {"error": "Blockchain recording is not available."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            user = request.user
            company = user.get_active_company()

            if not company:
                return Response({"error": "No active company found for user"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if already subscribed to blockchain
            if company.blockchain_subscription_status:
                return Response(
                    {"error": "Company already has blockchain verification subscription"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get or create Stripe customer
            if hasattr(company, "subscription") and company.subscription.stripe_customer_id:
                customer_id = company.subscription.stripe_customer_id
            else:
                # Create new customer
                customer = stripe.Customer.create(
                    email=user.email, name=company.name, metadata={"company_id": company.id, "user_id": user.id}
                )
                customer_id = customer.id

                # Update subscription with customer ID if exists
                if hasattr(company, "subscription"):
                    company.subscription.stripe_customer_id = customer_id
                    company.subscription.save()

            # Look up the blockchain addon to use its Stripe price
            blockchain_addon = AddOn.objects.filter(slug="blockchain-verification", is_active=True).first()
            if not blockchain_addon or not blockchain_addon.stripe_price_id:
                return Response(
                    {"error": "Blockchain verification add-on is not configured"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Create checkout session for blockchain verification
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": blockchain_addon.stripe_price_id,
                        "quantity": 1,
                    }
                ],
                mode="subscription",
                success_url=f"{settings.FRONTEND_URL}/admin/dashboard/subscription?blockchain_subscription=success&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{settings.FRONTEND_URL}/admin/dashboard/subscription?blockchain_subscription=cancelled",
                metadata={"company_id": company.id, "user_id": user.id, "subscription_type": "blockchain_verification"},
            )

            logger.info(
                f"Created blockchain subscription checkout session for company {company.id}: {checkout_session.id}"
            )

            return Response({"checkout_url": checkout_session.url, "session_id": checkout_session.id})

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating blockchain subscription: {str(e)}")
            return Response(
                {"error": "Payment processing error. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(f"Error creating blockchain subscription: {str(e)}")
            return Response({"error": "An unexpected error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BlockchainSubscriptionStatusView(APIView):
    """Get blockchain subscription status"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get blockchain subscription status for user's company
        GET /api/billing/subscription-status/

        Query Parameters:
            sync (bool): If true, validates status against Stripe (slower but authoritative)
        """
        try:
            user = request.user
            company = user.get_active_company()

            if not company:
                return Response({"error": "No active company found for user"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if we should sync with Stripe
            should_sync = request.query_params.get("sync", "").lower() in ["true", "1", "yes"]
            session_id = request.query_params.get("session_id", "")

            # Get blockchain subscription status
            blockchain_subscribed = company.blockchain_subscription_status
            stripe_validated = False

            # Optional: Validate against Stripe if requested
            if should_sync:
                # Method 1: Validate via session_id (best for post-checkout sync)
                if session_id and session_id.startswith("cs_"):
                    try:
                        session_status = self._validate_blockchain_session(session_id, company.id)
                        if session_status:
                            stripe_validated = True
                            if not blockchain_subscribed:
                                logger.info(
                                    f"Activating blockchain subscription for company {company.id} "
                                    f"via session validation: {session_id}"
                                )
                                company.blockchain_subscription_status = True
                                company.save()
                                blockchain_subscribed = True
                    except Exception as e:
                        logger.error(f"Error validating blockchain session {session_id}: {str(e)}")

                # Method 2: Validate via customer_id (for regular sync)
                elif hasattr(company, "subscription") and company.subscription.stripe_customer_id:
                    try:
                        stripe_blockchain_status = self._validate_blockchain_with_stripe(
                            company.subscription.stripe_customer_id
                        )
                        if stripe_blockchain_status is not None:
                            stripe_validated = True
                            # Update database if out of sync
                            if blockchain_subscribed != stripe_blockchain_status:
                                logger.warning(
                                    f"Blockchain status mismatch for company {company.id}: "
                                    f"DB={blockchain_subscribed}, Stripe={stripe_blockchain_status}. Updating DB."
                                )
                                company.blockchain_subscription_status = stripe_blockchain_status
                                company.save()
                                blockchain_subscribed = stripe_blockchain_status
                    except Exception as e:
                        logger.error(f"Error validating blockchain status with Stripe: {str(e)}")

            # Get main subscription info if exists
            main_subscription_info = {}
            if hasattr(company, "subscription"):
                subscription = company.subscription
                main_subscription_info = {
                    "plan_name": subscription.plan.name,
                    "status": subscription.status,
                    "current_period_end": (
                        subscription.current_period_end.isoformat() if subscription.current_period_end else None
                    ),
                    "cancel_at_period_end": subscription.cancel_at_period_end,
                }

            return Response(
                {
                    "blockchainSubscribed": blockchain_subscribed,
                    "stripeValidated": stripe_validated,
                    "company": {"id": company.id, "name": company.name},
                    "mainSubscription": main_subscription_info,
                }
            )

        except Exception as e:
            logger.error(f"Error getting subscription status: {str(e)}", exc_info=True)
            return Response({"error": "An unexpected error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _validate_blockchain_with_stripe(self, stripe_customer_id):
        """
        Validate blockchain subscription status against Stripe.
        Returns True if active blockchain subscription found, False if not, None if can't determine.
        """
        try:
            # List all subscriptions for this customer
            subscriptions = stripe.Subscription.list(customer=stripe_customer_id, status="active")
            # Look up blockchain addon price from DB
            blockchain_addon = AddOn.objects.filter(slug="blockchain-verification", is_active=True).first()
            blockchain_price_id = blockchain_addon.stripe_price_id if blockchain_addon else None

            for subscription in subscriptions.data:
                # Check subscription metadata first
                if subscription.metadata.get("subscription_type") == "blockchain_verification":
                    return True

                # Check line items by price ID
                if blockchain_price_id:
                    line_items = stripe.Subscription.list_line_items(subscription.id)
                    for item in line_items.data:
                        if item.price.id == blockchain_price_id:
                            return True

            return False
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error during blockchain validation: {str(e)}")
            return None

    def _validate_blockchain_session(self, session_id, company_id):
        """
        Validate blockchain subscription via Stripe checkout session.
        Returns True if the session is complete and belongs to the company.

        Security measures (2025 best practices):
        - Server-side validation against Stripe API (never trust client)
        - Company ownership verification (prevents account hijacking)
        - Session type verification (prevents cross-session attacks)
        - Time-based validation (prevents old session replay)
        - Status verification (prevents incomplete payment fraud)
        """
        import time

        try:
            # Retrieve the checkout session from Stripe
            session = stripe.checkout.Session.retrieve(session_id)

            # Security: Validate session is complete
            if session.status != "complete":
                logger.warning(f"Blockchain session {session_id} is not complete: {session.status}")
                return False

            # Security: Time-based validation - reject sessions older than 1 hour
            # This prevents replay attacks with old session IDs
            session_age_seconds = time.time() - session.created
            max_age_seconds = 3600  # 1 hour
            if session_age_seconds > max_age_seconds:
                logger.warning(
                    f"Blockchain session {session_id} is too old: " f"{session_age_seconds:.0f}s > {max_age_seconds}s"
                )
                return False

            # Security: Validate it's for the correct company (ownership check)
            session_company_id = session.metadata.get("company_id")
            if str(session_company_id) != str(company_id):
                logger.warning(
                    f"Blockchain session {session_id} company mismatch: "
                    f"expected {company_id}, got {session_company_id}"
                )
                return False

            # Security: Validate it's a blockchain subscription (type check)
            if session.metadata.get("subscription_type") != "blockchain_verification":
                logger.warning(f"Session {session_id} is not a blockchain subscription")
                return False

            logger.info(f"Blockchain session {session_id} validated successfully for company {company_id}")
            return True

        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error validating session {session_id}: {str(e)}")
            return False
