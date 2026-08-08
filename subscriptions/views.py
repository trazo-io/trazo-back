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

from company.models import Company
from company.serializers import RetrieveCompanySerializer

from .models import AddOn, Invoice, PaymentMethod, Plan, ProcessedWebhookEvent, Subscription, SubscriptionAddOn
from .permissions import IsCompanyAdminForSubscription
from .serializers import (
    AddOnSerializer,
    InvoiceSerializer,
    PaymentMethodSerializer,
    PlanSerializer,
    SubscriptionSerializer,
)

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


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


class SubscriptionViewSet(viewsets.ModelViewSet):
    """API endpoint for managing subscriptions"""

    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        # Billing operations require Company Admin role
        write_actions = [
            "cancel",
            "reactivate",
            "change_plan",
            "add_addon",
            "create_session",
            "create_customer_portal_session",
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
        """Return all billing data in a single request"""
        try:
            user = request.user
            companies = user.companies.all()

            # Get subscription - typically just one per user/company
            subscriptions = (
                self.get_queryset().select_related("plan", "pending_plan", "company").prefetch_related("addons__addon")
            )
            subscription = subscriptions.first() if subscriptions.exists() else None

            # Get available add-ons
            addons = AddOn.objects.filter(is_active=True)

            # Get payment methods for user's companies
            payment_methods = PaymentMethod.objects.filter(company__in=companies)

            # Get invoices for user's companies
            invoices = Invoice.objects.filter(company__in=companies).order_by("-invoice_date")

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
        """Start a free 14-day Starter trial.
        Creates a local subscription with no Stripe involvement."""
        user = request.user
        company_id = request.data.get("company_id")

        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)

        # Check user belongs to company
        if not user.companies.filter(id=company.id).exists():
            return Response({"error": "Not authorized"}, status=status.HTTP_403_FORBIDDEN)

        # Check company doesn't already have a subscription (trial is one-time)
        if hasattr(company, "subscription") or Subscription.objects.filter(company=company).exists():
            return Response(
                {"error": "Company already has or had a subscription. Trial is one-time only."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the Starter plan
        starter_plan = Plan.objects.filter(slug="starter", is_active=True).first()
        if not starter_plan:
            return Response(
                {"error": "Starter plan not available"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Create local-only subscription (no Stripe)
        now = timezone.now()
        trial_end = now + timezone.timedelta(days=settings.TRIAL_PERIOD_DAYS)

        subscription = Subscription.objects.create(
            company=company,
            plan=starter_plan,
            status="trialing",
            current_period_start=now,
            current_period_end=trial_end,
            trial_end=trial_end,
        )

        logger.info(
            "Starter trial created: Company %s, trial ends %s",
            company.id,
            trial_end.isoformat(),
        )

        return Response(
            {
                "status": "Trial started successfully",
                "subscription": SubscriptionSerializer(subscription).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel subscription at the end of billing period"""
        subscription = self.get_object()

        try:
            if subscription.stripe_subscription_id:
                stripe_subscription = stripe.Subscription.modify(
                    subscription.stripe_subscription_id, cancel_at_period_end=True
                )

            subscription.cancel_at_period_end = True
            subscription.save()

            return Response(
                {
                    "status": "subscription will be canceled at the end of the billing period",
                    "end_date": subscription.current_period_end,
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
                stripe_subscription = stripe.Subscription.modify(
                    subscription.stripe_subscription_id, cancel_at_period_end=False
                )

            subscription.cancel_at_period_end = False
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
        """Add an add-on to the subscription with Stripe checkout"""
        subscription = self.get_object()
        addon_id = request.data.get("addon_id")
        quantity = int(request.data.get("quantity", 1))
        return_url = request.data.get("return_url", None)

        # Better validation
        if not addon_id:
            return Response({"error": "addon_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        if quantity <= 0:
            return Response({"error": "quantity must be greater than 0"}, status=status.HTTP_400_BAD_REQUEST)

        # Add request logging for debugging
        logger.info(
            f"Creating checkout session for addon {addon_id} with quantity {quantity} to subscription {subscription.id}"
        )

        try:
            addon = AddOn.objects.get(id=addon_id, is_active=True)

            # Get the frontend URL from settings or use a default
            frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")

            # Create a Stripe checkout session for the add-on
            # CRITICAL: Include session_id and company_id for frontend verification
            # {CHECKOUT_SESSION_ID} is a Stripe placeholder that gets replaced with actual session ID
            success_url_params = (
                f"success=true&session_id={{CHECKOUT_SESSION_ID}}"
                f"&company_id={str(subscription.company.id)}&from_addon=true"
            )

            # If return_url is provided, URL-encode it to prevent param collision
            if return_url:
                from urllib.parse import quote

                success_url_params += f"&return_url={quote(return_url, safe='')}"

            success_url = f"{frontend_url}/admin/dashboard/stripe-success?{success_url_params}"
            cancel_url = f"{frontend_url}/admin/dashboard/subscription"

            # Create the checkout session
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": addon.stripe_price_id,
                        "quantity": quantity,
                    }
                ],
                mode="subscription",
                customer=subscription.stripe_customer_id,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "company_id": str(subscription.company.id),
                    "subscription_id": str(subscription.id),
                    "addon_id": str(addon.id),
                    "quantity": str(quantity),
                    "addon_type": addon.slug,
                    "is_addon_purchase": "true",
                    "return_url": return_url,
                },
            )

            # Return the session URL
            logger.info(f"Created checkout session: {checkout_session.id}")
            return Response({"url": checkout_session.url, "session_id": checkout_session.id})

        except AddOn.DoesNotExist:
            logger.error("Addon not found: %s", addon_id)
            return Response({"error": "Add-on not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("Error creating checkout session for add-on: %s", e, exc_info=True)
            return Response(
                {"error": "Failed to create add-on checkout. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
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

            # Verify user has permission to manage this company
            if not request.user.is_staff and company not in request.user.companies.all():
                return Response(
                    {"error": "You do not have permission to manage this company"}, status=status.HTTP_403_FORBIDDEN
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
                # Make sure the company has an active subscription
                if not hasattr(company, "subscription") or not company.subscription.stripe_subscription_id:
                    return Response(
                        {"error": "Company must have an active subscription to purchase add-ons"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Get the add-on
                addon_slug_map = {
                    "extraEstablishment": "extra-establishment",
                    "extraProduction": "extra-production",
                    "extraParcel": "extra-parcel",
                    "extraStorage": "extra-storage",
                }

                try:
                    addon = AddOn.objects.get(slug=addon_slug_map[addon_type], is_active=True)
                except AddOn.DoesNotExist:
                    return Response({"error": "Add-on not found"}, status=status.HTTP_404_NOT_FOUND)

                # Determine success and cancel URLs
                success_url_params = (
                    f"success=true&session_id={{CHECKOUT_SESSION_ID}}&company_id={str(company.id)}&addon=true"
                )

                # Add return_url parameter if provided
                if success_url:
                    success_url_params += f"&return_url={success_url}"

                success_url_final = (
                    success_url or f"{settings.FRONTEND_URL}/admin/dashboard/stripe-success?{success_url_params}"
                )
                cancel_url_final = cancel_url or f"{settings.FRONTEND_URL}/admin/dashboard/plan-usage?canceled=true"

                # Create checkout session for add-on
                checkout_session = stripe.checkout.Session.create(
                    customer=customer_id,
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price": addon.stripe_price_id,
                            "quantity": quantity,
                        }
                    ],
                    mode="subscription",  # Add-on prices are recurring
                    success_url=success_url_final,
                    cancel_url=cancel_url_final,
                    metadata={
                        "company_id": company.id,
                        "addon_id": addon.id,
                        "quantity": quantity,
                        "addon_type": addon_type,
                        "return_url": success_url,
                    },
                )

                return Response({"url": checkout_session.url})

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

            # Verify user has permission to manage this company
            if not request.user.is_staff and company not in request.user.companies.all():
                return Response(
                    {"error": "You do not have permission to manage this company"}, status=status.HTTP_403_FORBIDDEN
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

        # Update subscription status
        if subscription.status == "active":
            subscription.status = "past_due"
            subscription.save()

    except Exception as e:
        logger.exception("Error in handle_invoice_payment_failed: %s", e)
        raise


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

        # Update subscription status
        subscription.status = "canceled"
        subscription.save()

        # Send cancellation email
        try:
            company = subscription.company
            admin_user = company.company_admins.first()
            if admin_user:
                # Import email utility function
                from subscriptions.utils import send_subscription_canceled_email

                send_subscription_canceled_email(admin_user.email, admin_user.first_name, company.name)
        except Exception as e:
            logger.error("Error sending cancellation email: %s", str(e))

    except Exception as e:
        logger.exception("Error in handle_customer_subscription_deleted: %s", e)
        raise


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
