"""
Test cases for enhanced public views tracking with bot filtering and unique visitor detection
"""

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import RequestFactory, TestCase

from company.models import Company, Establishment
from history.models import History
from product.models import Product


class PublicViewsTrackingTestCase(TestCase):
    """Test enhanced public views tracking functionality"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()

        # Create test company and establishment
        self.company = Company.objects.create(name="Test Farm Co")

        self.establishment = Establishment.objects.create(company=self.company, name="Test Farm", year_established=2020)

        # Create test product
        self.product = Product.objects.create(name="Test Crop", parcel_id=1)  # Assuming a parcel exists

        # Create test production
        self.production = History.objects.create(
            name="Test Production 2024", product=self.product, published=True, public_views=0, unique_visitors=0
        )

    def test_basic_view_increment(self):
        """Test basic view increment functionality"""
        initial_views = self.production.public_views
        initial_visitors = self.production.unique_visitors

        # Create a basic request
        request = self.factory.get("/test/")
        request.session = SessionStore()
        request.session.create()

        # Increment views
        result = self.production.increment_public_views(request)

        # Verify results
        self.assertTrue(result["views_incremented"])
        self.assertTrue(result["unique_visitor"])  # Should be unique on first visit
        self.assertEqual(self.production.public_views, initial_views + 1)
        self.assertEqual(self.production.unique_visitors, initial_visitors + 1)

    def test_repeat_visitor(self):
        """Test that repeat visitors don't increment unique count"""
        # Create request with session
        request = self.factory.get("/test/")
        request.session = SessionStore()
        request.session.create()

        # First visit
        result1 = self.production.increment_public_views(request)
        self.assertTrue(result1["unique_visitor"])

        # Second visit with same session
        result2 = self.production.increment_public_views(request)
        self.assertFalse(result2["unique_visitor"])  # Not unique anymore
        self.assertTrue(result2["views_incremented"])  # But views still increment

        # Verify counts
        self.assertEqual(self.production.public_views, 2)
        self.assertEqual(self.production.unique_visitors, 1)  # Only 1 unique

    def test_bot_detection(self):
        """Test bot detection functionality"""
        bot_user_agents = [
            "Googlebot/2.1 (+http://www.google.com/bot.html)",
            "facebookexternalhit/1.1",
            "Twitterbot/1.0",
            "LinkedInBot/1.0",
            "WhatsApp/2.0",
            "bingbot/2.0",
            "YandexBot/3.0",
            "BaiduSpider/2.0",
        ]

        initial_views = self.production.public_views

        for user_agent in bot_user_agents:
            request = self.factory.get("/test/")
            request.META["HTTP_USER_AGENT"] = user_agent
            request.session = SessionStore()
            request.session.create()

            result = self.production.increment_public_views(request)

            # Bot requests should be rejected
            self.assertFalse(result["views_incremented"])
            self.assertEqual(result["reason"], "bot_detected")

        # Views should not have changed
        self.assertEqual(self.production.public_views, initial_views)

    def test_human_user_agents(self):
        """Test that human user agents are properly handled"""
        human_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
            "Mozilla/5.0 (Android 11; Mobile; rv:89.0) Gecko/89.0",
        ]

        for user_agent in human_user_agents:
            request = self.factory.get("/test/")
            request.META["HTTP_USER_AGENT"] = user_agent
            request.session = SessionStore()
            request.session.create()

            initial_views = self.production.public_views
            result = self.production.increment_public_views(request)

            # Human requests should be accepted
            self.assertTrue(result["views_incremented"])
            self.assertTrue(result["unique_visitor"])
            self.assertEqual(self.production.public_views, initial_views + 1)

    def test_skip_bot_check(self):
        """Test skip_bot_check parameter"""
        request = self.factory.get("/test/")
        request.META["HTTP_USER_AGENT"] = "Googlebot/2.1"
        request.session = SessionStore()
        request.session.create()

        initial_views = self.production.public_views

        # With bot check (default) - should be rejected
        result1 = self.production.increment_public_views(request)
        self.assertFalse(result1["views_incremented"])

        # Skip bot check - should be accepted
        result2 = self.production.increment_public_views(request, skip_bot_check=True)
        self.assertTrue(result2["views_incremented"])
        self.assertEqual(self.production.public_views, initial_views + 1)

    def test_no_session_handling(self):
        """Test handling requests without sessions"""
        request = self.factory.get("/test/")
        # Don't add session to request

        initial_views = self.production.public_views
        result = self.production.increment_public_views(request)

        # Should still increment views, but not track as unique visitor
        self.assertTrue(result["views_incremented"])
        self.assertFalse(result["unique_visitor"])
        self.assertEqual(self.production.public_views, initial_views + 1)
        self.assertEqual(self.production.unique_visitors, 0)  # No unique tracking without session

    def test_concurrent_view_increments(self):
        """Test atomic increments prevent race conditions"""
        import threading
        from time import sleep

        initial_views = self.production.public_views
        results = []

        def increment_views():
            request = self.factory.get("/test/")
            request.session = SessionStore()
            request.session.create()
            result = self.production.increment_public_views(request)
            results.append(result)

        # Create multiple threads to simulate concurrent requests
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=increment_views)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all increments succeeded and final count is correct
        self.assertEqual(len([r for r in results if r["views_incremented"]]), 5)
        self.production.refresh_from_db()
        self.assertEqual(self.production.public_views, initial_views + 5)
