"""
Simple test for enhanced public views tracking functionality
"""

from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase

from history.models import History


class SimplePublicViewsTestCase(TestCase):
    """Simple test for public views tracking"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()

        # Create minimal production for testing
        self.production = History.objects.create(
            name="Test Production", published=True, public_views=0, unique_visitors=0
        )

    def test_bot_detection(self):
        """Test bot detection functionality"""
        # Test with a bot user agent
        request = self.factory.get("/test/")
        request.META["HTTP_USER_AGENT"] = "Googlebot/2.1 (+http://www.google.com/bot.html)"
        request.session = SessionStore()
        request.session.create()

        initial_views = self.production.public_views
        result = self.production.increment_public_views(request)

        # Bot requests should be rejected
        self.assertFalse(result["views_incremented"])
        self.assertEqual(result["reason"], "bot_detected")

        # Views should not have changed
        self.production.refresh_from_db()
        self.assertEqual(self.production.public_views, initial_views)

    def test_human_user_agent(self):
        """Test that human user agents work"""
        request = self.factory.get("/test/")
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        request.session = SessionStore()
        request.session.create()

        initial_views = self.production.public_views
        result = self.production.increment_public_views(request)

        # Human requests should be accepted
        self.assertTrue(result["views_incremented"])
        self.assertTrue(result["unique_visitor"])

        # Verify database update
        self.production.refresh_from_db()
        self.assertEqual(self.production.public_views, initial_views + 1)
        self.assertEqual(self.production.unique_visitors, 1)

    def test_repeat_visitor(self):
        """Test repeat visitor handling"""
        request = self.factory.get("/test/")
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        request.session = SessionStore()
        request.session.create()

        # First visit
        result1 = self.production.increment_public_views(request)
        self.assertTrue(result1["unique_visitor"])

        # Second visit with same session
        result2 = self.production.increment_public_views(request)
        self.assertFalse(result2["unique_visitor"])  # Not unique anymore
        self.assertTrue(result2["views_incremented"])  # But views still increment

        # Verify final counts
        self.production.refresh_from_db()
        self.assertEqual(self.production.public_views, 2)
        self.assertEqual(self.production.unique_visitors, 1)  # Only 1 unique
