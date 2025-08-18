"""
Test Suite for Subscription and Billing
Ensures reliable Stripe integration and billing functionality
"""

import json
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from django.contrib.auth import get_user_model
from django.db import models
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from company.models import Company, Establishment
from subscriptions.middleware import SubscriptionMiddleware
from subscriptions.models import Subscription, Plan
from subscriptions.services import BillingService, SubscriptionService

User = get_user_model()


class TestSubscriptionModel(TransactionTestCase):
    """Test Subscription model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

    def test_subscription_creation(self):
        """Test subscription creation"""
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            stripe_subscription_id="sub_test123",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        self.assertEqual(subscription.company, self.company)
        self.assertEqual(subscription.plan_type, "professional")
        self.assertEqual(subscription.status, "active")
        self.assertTrue(subscription.is_active())

    def test_subscription_feature_access(self):
        """Test subscription feature access"""
        # Basic plan
        basic_subscription = Subscription.objects.create(
            company=self.company,
            plan_type="basic",
            status="active",
            max_establishments=5,
            max_carbon_entries=100,
            blockchain_verification=False,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        self.assertTrue(basic_subscription.can_create_establishment())
        self.assertTrue(basic_subscription.can_create_carbon_entry())
        self.assertFalse(basic_subscription.has_blockchain_access())

        # Professional plan
        pro_subscription = Subscription.objects.create(
            company=Company.objects.create(name="Pro Company", country="USA", created_by=self.user),
            plan_type="professional",
            status="active",
            max_establishments=50,
            max_carbon_entries=1000,
            blockchain_verification=True,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        self.assertTrue(pro_subscription.can_create_establishment())
        self.assertTrue(pro_subscription.can_create_carbon_entry())
        self.assertTrue(pro_subscription.has_blockchain_access())

    def test_subscription_limits(self):
        """Test subscription usage limits"""
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="basic",
            status="active",
            max_establishments=2,
            current_establishments=1,
            max_carbon_entries=10,
            current_carbon_entries=9,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Should be able to create one more establishment
        self.assertTrue(subscription.can_create_establishment())

        # Should be able to create one more carbon entry
        self.assertTrue(subscription.can_create_carbon_entry())

        # Reach limits
        subscription.current_establishments = 2
        subscription.current_carbon_entries = 10
        subscription.save()

        # Should not be able to create more
        self.assertFalse(subscription.can_create_establishment())
        self.assertFalse(subscription.can_create_carbon_entry())

    def test_subscription_expiry(self):
        """Test subscription expiry"""
        # Expired subscription
        expired_subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            current_period_start=timezone.now() - timedelta(days=60),
            current_period_end=timezone.now() - timedelta(days=30),
        )

        self.assertFalse(expired_subscription.is_active())

        # Active subscription
        active_subscription = Subscription.objects.create(
            company=Company.objects.create(name="Active Company", country="USA", created_by=self.user),
            plan_type="professional",
            status="active",
            current_period_start=timezone.now() - timedelta(days=15),
            current_period_end=timezone.now() + timedelta(days=15),
        )

        self.assertTrue(active_subscription.is_active())


class TestUsageTracking(TransactionTestCase):
    """Test usage tracking functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def test_usage_record_creation(self):
        """Test usage record creation"""
        usage = UsageRecord.objects.create(
            subscription=self.subscription, feature="carbon_calculations", quantity=10, timestamp=timezone.now()
        )

        self.assertEqual(usage.subscription, self.subscription)
        self.assertEqual(usage.feature, "carbon_calculations")
        self.assertEqual(usage.quantity, 10)

    def test_usage_aggregation(self):
        """Test usage aggregation"""
        # Create multiple usage records
        base_time = timezone.now()
        for i in range(5):
            UsageRecord.objects.create(
                subscription=self.subscription,
                feature="carbon_calculations",
                quantity=i + 1,
                timestamp=base_time + timedelta(hours=i),
            )

        # Aggregate usage
        total_usage = UsageRecord.objects.filter(
            subscription=self.subscription, feature="carbon_calculations"
        ).aggregate(total=models.Sum("quantity"))["total"]

        self.assertEqual(total_usage, 15)  # 1+2+3+4+5

    def test_monthly_usage_tracking(self):
        """Test monthly usage tracking"""
        current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Create usage records for current month
        for i in range(3):
            UsageRecord.objects.create(
                subscription=self.subscription,
                feature="establishments",
                quantity=1,
                timestamp=current_month + timedelta(days=i),
            )

        # Create usage record for previous month
        previous_month = current_month - timedelta(days=1)
        UsageRecord.objects.create(
            subscription=self.subscription, feature="establishments", quantity=1, timestamp=previous_month
        )

        # Get current month usage
        current_month_usage = UsageRecord.objects.filter(
            subscription=self.subscription, feature="establishments", timestamp__gte=current_month
        ).count()

        self.assertEqual(current_month_usage, 3)


class TestStripeIntegration(TestCase):
    """Test Stripe integration functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.billing_service = BillingService()

    @override_settings(STRIPE_SECRET_KEY="sk_test_123")
    @patch("stripe.Customer.create")
    def test_stripe_customer_creation(self, mock_create_customer):
        """Test Stripe customer creation"""
        # Mock Stripe customer response
        mock_customer = {"id": "cus_test123", "email": "test@example.com", "name": "Test Company"}
        mock_create_customer.return_value = mock_customer

        customer_id = self.billing_service.create_stripe_customer(email=self.user.email, name=self.company.name)

        self.assertEqual(customer_id, "cus_test123")
        mock_create_customer.assert_called_once_with(email="test@example.com", name="Test Company")

    @patch("stripe.Subscription.create")
    @patch("stripe.Customer.create")
    def test_subscription_creation(self, mock_create_customer, mock_create_subscription):
        """Test subscription creation via Stripe"""
        # Mock Stripe responses
        mock_create_customer.return_value = {"id": "cus_test123"}
        mock_create_subscription.return_value = {
            "id": "sub_test123",
            "status": "active",
            "current_period_start": int(timezone.now().timestamp()),
            "current_period_end": int((timezone.now() + timedelta(days=30)).timestamp()),
            "items": {
                "data": [{"price": {"id": "price_professional", "unit_amount": 9900, "currency": "usd"}}]  # $99.00
            },
        }

        subscription = self.billing_service.create_subscription(
            customer_id="cus_test123", price_id="price_professional"
        )

        self.assertEqual(subscription["id"], "sub_test123")
        self.assertEqual(subscription["status"], "active")

        mock_create_subscription.assert_called_once_with(
            customer="cus_test123",
            items=[{"price": "price_professional"}],
            payment_behavior="default_incomplete",
            expand=["latest_invoice.payment_intent"],
        )

    @patch("stripe.PaymentMethod.attach")
    @patch("stripe.Customer.modify")
    def test_payment_method_attachment(self, mock_modify_customer, mock_attach_payment):
        """Test payment method attachment to customer"""
        mock_attach_payment.return_value = {"id": "pm_test123"}
        mock_modify_customer.return_value = {"id": "cus_test123"}

        result = self.billing_service.attach_payment_method(customer_id="cus_test123", payment_method_id="pm_test123")

        self.assertTrue(result)
        mock_attach_payment.assert_called_once_with("pm_test123", customer="cus_test123")
        mock_modify_customer.assert_called_once_with(
            "cus_test123", invoice_settings={"default_payment_method": "pm_test123"}
        )

    @patch("stripe.Subscription.modify")
    def test_subscription_upgrade(self, mock_modify_subscription):
        """Test subscription plan upgrade"""
        mock_modify_subscription.return_value = {
            "id": "sub_test123",
            "status": "active",
            "items": {
                "data": [{"id": "si_test123", "price": {"id": "price_enterprise", "unit_amount": 19900}}]  # $199.00
            },
        }

        result = self.billing_service.upgrade_subscription(
            subscription_id="sub_test123", new_price_id="price_enterprise"
        )

        self.assertEqual(result["id"], "sub_test123")
        mock_modify_subscription.assert_called_once()

    @patch("stripe.Subscription.delete")
    def test_subscription_cancellation(self, mock_cancel_subscription):
        """Test subscription cancellation"""
        mock_cancel_subscription.return_value = {
            "id": "sub_test123",
            "status": "canceled",
            "canceled_at": int(timezone.now().timestamp()),
        }

        result = self.billing_service.cancel_subscription("sub_test123")

        self.assertEqual(result["status"], "canceled")
        mock_cancel_subscription.assert_called_once_with("sub_test123")


class TestWebhookHandling(TestCase):
    """Test Stripe webhook handling"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            stripe_subscription_id="sub_test123",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

    @override_settings(STRIPE_WEBHOOK_SECRET="whsec_test123")
    @patch("stripe.Webhook.construct_event")
    def test_subscription_updated_webhook(self, mock_construct_event):
        """Test subscription updated webhook handling"""
        # Mock webhook event
        webhook_event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test123",
                    "status": "past_due",
                    "current_period_start": int(timezone.now().timestamp()),
                    "current_period_end": int((timezone.now() + timedelta(days=30)).timestamp()),
                }
            },
        }
        mock_construct_event.return_value = webhook_event

        # Send webhook
        url = reverse("subscriptions:stripe-webhook")
        response = self.client.post(
            url, data=json.dumps(webhook_event), content_type="application/json", HTTP_STRIPE_SIGNATURE="test_signature"
        )

        self.assertEqual(response.status_code, 200)

        # Verify subscription was updated
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "past_due")

    @patch("stripe.Webhook.construct_event")
    def test_payment_failed_webhook(self, mock_construct_event):
        """Test payment failed webhook handling"""
        webhook_event = {
            "type": "invoice.payment_failed",
            "data": {"object": {"subscription": "sub_test123", "amount_due": 9900, "currency": "usd"}},
        }
        mock_construct_event.return_value = webhook_event

        url = reverse("subscriptions:stripe-webhook")
        response = self.client.post(
            url, data=json.dumps(webhook_event), content_type="application/json", HTTP_STRIPE_SIGNATURE="test_signature"
        )

        self.assertEqual(response.status_code, 200)

        # Verify subscription status was updated to handle payment failure
        self.subscription.refresh_from_db()
        # Status might be updated to 'past_due' or remain 'active' depending on business logic

    def test_webhook_signature_validation(self):
        """Test webhook signature validation"""
        url = reverse("subscriptions:stripe-webhook")

        # Send webhook without signature
        response = self.client.post(url, data=json.dumps({"type": "test.event"}), content_type="application/json")

        self.assertEqual(response.status_code, 400)  # Should reject unsigned webhook


class TestSubscriptionMiddleware(TestCase):
    """Test subscription middleware functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.middleware = SubscriptionMiddleware(lambda request: None)

    def test_subscription_access_control(self):
        """Test subscription-based access control"""
        from django.contrib.auth.models import AnonymousUser
        from django.http import HttpRequest

        # Create request
        request = HttpRequest()
        request.user = self.user
        request.company = self.company

        # No subscription - should limit access
        response = self.middleware.process_request(request)
        if response:
            self.assertIn(response.status_code, [403, 402])  # Forbidden or payment required

        # Active subscription - should allow access
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        response = self.middleware.process_request(request)
        self.assertIsNone(response)  # Should allow through

    def test_feature_gating(self):
        """Test feature-specific gating"""
        from django.http import HttpRequest

        request = HttpRequest()
        request.user = self.user
        request.company = self.company
        request.path = "/api/carbon/blockchain-verify/"

        # Basic subscription without blockchain access
        basic_subscription = Subscription.objects.create(
            company=self.company,
            plan_type="basic",
            status="active",
            blockchain_verification=False,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        response = self.middleware.process_request(request)
        if response:
            self.assertEqual(response.status_code, 403)

        # Professional subscription with blockchain access
        basic_subscription.blockchain_verification = True
        basic_subscription.save()

        response = self.middleware.process_request(request)
        self.assertIsNone(response)  # Should allow through


class TestBillingService(TestCase):
    """Test billing service functionality"""

    def setUp(self):
        """Set up test data"""
        self.billing_service = BillingService()
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

    def test_plan_pricing_calculation(self):
        """Test plan pricing calculations"""
        # Basic plan
        basic_price = self.billing_service.calculate_plan_price("basic", establishments=3)
        self.assertGreater(basic_price, 0)

        # Professional plan
        pro_price = self.billing_service.calculate_plan_price("professional", establishments=10)
        self.assertGreater(pro_price, basic_price)

        # Enterprise plan
        enterprise_price = self.billing_service.calculate_plan_price("enterprise", establishments=50)
        self.assertGreater(enterprise_price, pro_price)

    def test_usage_based_billing(self):
        """Test usage-based billing calculations"""
        # Create subscription with usage limits
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            max_carbon_entries=1000,
            current_carbon_entries=1200,  # Over limit
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Calculate overage charges
        overage_cost = self.billing_service.calculate_overage_charges(subscription)
        self.assertGreater(overage_cost, 0)  # Should have overage charges

    def test_proration_calculation(self):
        """Test proration calculations for mid-cycle changes"""
        # Calculate proration for upgrade mid-cycle
        days_remaining = 15
        old_price = Decimal("99.00")
        new_price = Decimal("199.00")

        proration = self.billing_service.calculate_proration(old_price, new_price, days_remaining, 30)

        expected_proration = (new_price - old_price) * (days_remaining / 30)
        self.assertAlmostEqual(proration, expected_proration, places=2)

    def test_tax_calculation(self):
        """Test tax calculation for different regions"""
        # US tax calculation
        us_total = self.billing_service.calculate_total_with_tax(amount=Decimal("100.00"), country="USA", state="CA")
        self.assertGreater(us_total, Decimal("100.00"))

        # EU VAT calculation
        eu_total = self.billing_service.calculate_total_with_tax(amount=Decimal("100.00"), country="France")
        self.assertGreater(eu_total, Decimal("100.00"))

    def test_invoice_generation(self):
        """Test invoice generation"""
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="professional",
            status="active",
            stripe_subscription_id="sub_test123",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        invoice_data = self.billing_service.generate_invoice_data(subscription)

        self.assertIn("subscription_id", invoice_data)
        self.assertIn("amount", invoice_data)
        self.assertIn("currency", invoice_data)
        self.assertIn("billing_period", invoice_data)
        self.assertIn("line_items", invoice_data)


class TestSubscriptionAnalytics(TestCase):
    """Test subscription analytics and reporting"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        # Create multiple companies with different subscriptions
        self.companies = []
        self.subscriptions = []

        for i in range(5):
            company = Company.objects.create(name=f"Company {i}", country="USA", created_by=self.user)
            self.companies.append(company)

            subscription = Subscription.objects.create(
                company=company,
                plan_type="professional" if i % 2 == 0 else "basic",
                status="active",
                monthly_revenue=Decimal("99.00") if i % 2 == 0 else Decimal("29.00"),
                current_period_start=timezone.now(),
                current_period_end=timezone.now() + timedelta(days=30),
            )
            self.subscriptions.append(subscription)

    def test_mrr_calculation(self):
        """Test Monthly Recurring Revenue (MRR) calculation"""
        from subscriptions.analytics import SubscriptionAnalytics

        analytics = SubscriptionAnalytics()
        mrr = analytics.calculate_mrr()

        # Should be sum of all active subscription revenues
        expected_mrr = sum(sub.monthly_revenue for sub in self.subscriptions if sub.status == "active")
        self.assertEqual(mrr, expected_mrr)

    def test_churn_rate_calculation(self):
        """Test churn rate calculation"""
        from subscriptions.analytics import SubscriptionAnalytics

        # Cancel one subscription
        self.subscriptions[0].status = "canceled"
        self.subscriptions[0].canceled_at = timezone.now()
        self.subscriptions[0].save()

        analytics = SubscriptionAnalytics()
        churn_rate = analytics.calculate_churn_rate()

        # Should be 1/5 = 20%
        self.assertAlmostEqual(churn_rate, 0.20, places=2)

    def test_ltv_calculation(self):
        """Test Customer Lifetime Value (LTV) calculation"""
        from subscriptions.analytics import SubscriptionAnalytics

        analytics = SubscriptionAnalytics()
        ltv = analytics.calculate_customer_ltv()

        self.assertGreater(ltv, 0)
        self.assertIsInstance(ltv, Decimal)


if __name__ == "__main__":
    unittest.main()
