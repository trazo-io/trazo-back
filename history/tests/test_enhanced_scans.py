"""
Test suite for Enhanced Scan System (2025 Standards)
Tests privacy compliance, bot detection, deduplication, and analytics
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from history.models import History, HistoryScan
from history.services.analytics_service import AnalyticsService
from history.services.bot_detection_service import BotDetectionService
from history.services.deduplication_service import DeduplicationService
from history.services.privacy_service import GDPRComplianceService, PrivacyService
from history.views import PublicHistoryScanViewSet

User = get_user_model()


class TestPrivacyCompliance(TestCase):
    """Test GDPR compliance and privacy protection features"""

    def setUp(self):
        self.factory = RequestFactory()

    def test_ip_hashing(self):
        """Test IP address hashing for privacy"""
        ip = "192.168.1.100"
        hashed = PrivacyService.hash_ip(ip)

        # Should be a 64-character hex string (SHA-256)
        self.assertEqual(len(hashed), 64)
        self.assertRegex(hashed, r"^[a-f0-9]{64}$")

        # Same IP should produce same hash
        self.assertEqual(hashed, PrivacyService.hash_ip(ip))

        # Different IPs should produce different hashes
        different_hash = PrivacyService.hash_ip("192.168.1.101")
        self.assertNotEqual(hashed, different_hash)

    def test_session_fingerprinting(self):
        """Test privacy-safe session fingerprinting"""
        request = self.factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 Test Browser")
        fingerprint = PrivacyService.generate_session_fingerprint(request)

        # Should be a 64-character hex string
        self.assertEqual(len(fingerprint), 64)
        self.assertRegex(fingerprint, r"^[a-f0-9]{64}$")

    def test_consent_processing(self):
        """Test consent processing and data retention"""
        request = self.factory.post("/", {"city": "Test City", "country": "Test Country"})
        request.COOKIES = {"trazo-analytics-consent": "true"}

        privacy_data = PrivacyService.process_scan_consent(request)

        # Should include all required privacy fields
        self.assertIn("ip_hash", privacy_data)
        self.assertIn("session_hash", privacy_data)
        self.assertIn("consent_given", privacy_data)
        self.assertIn("data_retention_until", privacy_data)
        self.assertTrue(privacy_data["consent_given"])

    def test_gdpr_anonymization(self):
        """Test GDPR-compliant data anonymization"""
        # Create test scan
        scan = HistoryScan.objects.create(
            ip_hash="test_hash",
            session_hash="test_session",
            consent_given=True,
            data_retention_until=timezone.now() - timedelta(days=1),  # Expired
        )

        # Anonymize
        success = GDPRComplianceService.anonymize_scan(scan)
        self.assertTrue(success)

        # Refresh from database
        scan.refresh_from_db()

        # Should be anonymized
        self.assertEqual(scan.ip_hash, "ANONYMIZED")
        self.assertEqual(scan.session_hash, "ANONYMIZED")
        self.assertIsNone(scan.user)


class TestBotDetection(TestCase):
    """Test bot detection and security features"""

    def setUp(self):
        self.factory = RequestFactory()
        self.service = BotDetectionService()

    def test_bot_user_agent_detection(self):
        """Test detection of known bot user agents"""
        # Bot user agent
        bot_request = self.factory.get("/", HTTP_USER_AGENT="Googlebot/2.1")
        bot_score = self.service.calculate_bot_score(bot_request)
        self.assertGreater(bot_score, 0.8)

        # Human user agent
        human_request = self.factory.get(
            "/", HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        human_score = self.service.calculate_bot_score(human_request)
        self.assertLess(human_score, 0.5)

    def test_spam_content_detection(self):
        """Test spam content detection in comments"""
        spam_content = "Buy cheap products now! Click here: http://spam.com"
        self.assertTrue(self.service._contains_suspicious_content({"comment": spam_content}))

        normal_content = "Great product! Very sustainable farming practices."
        self.assertFalse(self.service._contains_suspicious_content({"comment": normal_content}))

    def test_human_verification(self):
        """Test human verification logic"""
        # Human-like request
        human_request = self.factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        self.assertTrue(self.service.is_verified_human(human_request))

        # Bot-like request
        bot_request = self.factory.get("/", HTTP_USER_AGENT="curl/7.68.0")
        self.assertFalse(self.service.is_verified_human(bot_request))


class TestSessionDeduplication(TestCase):
    """Test session deduplication functionality"""

    def setUp(self):
        self.service = DeduplicationService()

    def test_duplicate_detection(self):
        """Test duplicate scan detection"""
        # Create original scan
        original_scan = HistoryScan.objects.create(session_hash="test_session_123", history_id=1, date=timezone.now())

        # Check for duplicate within timeframe
        is_duplicate, found_scan = self.service.check_duplicate_scan("test_session_123", 1, timeframe_minutes=15)

        self.assertTrue(is_duplicate)
        self.assertEqual(found_scan.id, original_scan.id)

    def test_no_duplicate_outside_timeframe(self):
        """Test that old scans don't trigger duplicate detection"""
        # Create old scan
        old_scan = HistoryScan.objects.create(
            session_hash="test_session_456",
            history_id=1,
            date=timezone.now() - timedelta(hours=1),  # Outside 15-minute window
        )

        # Check for duplicate
        is_duplicate, found_scan = self.service.check_duplicate_scan("test_session_456", 1, timeframe_minutes=15)

        self.assertFalse(is_duplicate)
        self.assertIsNone(found_scan)

    def test_comprehensive_deduplication(self):
        """Test comprehensive deduplication with multiple strategies"""
        # Create original scan
        original_scan = HistoryScan.objects.create(
            session_hash="session_789", ip_hash="ip_hash_789", history_id=1, date=timezone.now()
        )

        # Test session-based deduplication
        is_duplicate, found_scan, method = self.service.check_comprehensive_duplicate("session_789", "different_ip", 1)

        self.assertTrue(is_duplicate)
        self.assertEqual(method, "session")
        self.assertEqual(found_scan.id, original_scan.id)


class TestAnalyticsService(TestCase):
    """Test privacy-safe analytics functionality"""

    def setUp(self):
        # Create test data
        self.history = History.objects.create(name="Test Production", published=True)

        # Create test scans with varying quality
        HistoryScan.objects.create(
            history=self.history, bot_score=0.1, engagement_score=0.8, is_duplicate=False, session_hash="session1"
        )

        HistoryScan.objects.create(
            history=self.history,
            bot_score=0.9,  # Bot-like
            engagement_score=0.1,
            is_duplicate=False,
            session_hash="session2",
        )

        HistoryScan.objects.create(
            history=self.history,
            bot_score=0.2,
            engagement_score=0.6,
            is_duplicate=True,  # Duplicate
            session_hash="session3",
        )

    def test_traffic_insights(self):
        """Test traffic analytics generation"""
        # Mock establishment ID
        establishment_id = 1

        with patch("history.services.analytics_service.HistoryScan.objects") as mock_scans:
            # Mock queryset behavior
            mock_scans.filter.return_value.select_related.return_value = HistoryScan.objects.filter(
                history=self.history, is_duplicate=False, bot_score__lt=0.5
            )

            insights = AnalyticsService.get_establishment_insights(establishment_id, 30)

            self.assertIn("traffic", insights)
            self.assertIn("total_scans", insights["traffic"])
            self.assertIn("unique_sessions", insights["traffic"])

    def test_quality_filtering(self):
        """Test that analytics exclude bots and duplicates"""
        quality_scans = HistoryScan.objects.filter(is_duplicate=False, bot_score__lt=0.5)

        # Should only include 1 scan (the high-quality one)
        self.assertEqual(quality_scans.count(), 1)

        quality_scan = quality_scans.first()
        self.assertEqual(quality_scan.bot_score, 0.1)
        self.assertEqual(quality_scan.engagement_score, 0.8)


class TestEnhancedScanCreation(TestCase):
    """Test the enhanced scan creation endpoint"""

    def setUp(self):
        self.factory = RequestFactory()
        self.viewset = PublicHistoryScanViewSet()

        # Create test history
        self.history = History.objects.create(name="Test Production", published=True)

    @patch("history.views.timezone")
    def test_successful_scan_creation(self, mock_timezone):
        """Test successful enhanced scan creation"""
        mock_timezone.now.return_value = timezone.now()

        request = self.factory.post(
            "/",
            {
                "production_id": str(self.history.id),
                "comment": "Great sustainable practices!",
                "time_on_page": 45,
                "interactions": 3,
            },
            HTTP_USER_AGENT="Mozilla/5.0 (Test Browser)",
        )

        request.COOKIES = {"trazo-analytics-consent": "true"}

        response = self.viewset.create(request)

        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.data)
        self.assertIn("message", response.data)

        # Verify scan was created with enhanced fields
        scan = HistoryScan.objects.get(id=response.data["id"])
        self.assertIsNotNone(scan.ip_hash)
        self.assertIsNotNone(scan.session_hash)
        self.assertTrue(scan.consent_given)
        self.assertGreater(scan.engagement_score, 0)

    def test_bot_blocking(self):
        """Test that bot requests are blocked"""
        request = self.factory.post(
            "/",
            {
                "production_id": str(self.history.id),
            },
            HTTP_USER_AGENT="Googlebot/2.1",
        )

        response = self.viewset.create(request)

        # Should be blocked
        self.assertEqual(response.status_code, 429)

    def test_consent_requirement(self):
        """Test that consent is required"""
        request = self.factory.post(
            "/",
            {
                "production_id": str(self.history.id),
            },
        )

        # No consent cookie
        response = self.viewset.create(request)

        self.assertEqual(response.status_code, 428)  # Precondition Required
        self.assertIn("consent_required", response.data)

    def test_input_validation(self):
        """Test input validation"""
        # Missing production_id
        request = self.factory.post("/", {})
        response = self.viewset.create(request)
        self.assertEqual(response.status_code, 400)

        # Invalid production_id
        request = self.factory.post("/", {"production_id": "invalid"})
        response = self.viewset.create(request)
        self.assertEqual(response.status_code, 400)

        # Comment too long
        request = self.factory.post(
            "/", {"production_id": str(self.history.id), "comment": "x" * 1001}  # Over 1000 character limit
        )
        response = self.viewset.create(request)
        self.assertEqual(response.status_code, 400)


class TestDataLifecycleManagement(TestCase):
    """Test automated data cleanup and lifecycle management"""

    def test_retention_date_calculation(self):
        """Test retention date calculation"""
        # Consented data
        retention_date = PrivacyService.calculate_retention_date(consent_given=True)
        self.assertGreater(retention_date, timezone.now())

        # Non-consented data
        deletion_date = PrivacyService.calculate_retention_date(consent_given=False)
        self.assertLess(deletion_date, timezone.now() + timedelta(days=8))

    def test_cleanup_query_generation(self):
        """Test that cleanup queries identify correct records"""
        # Create expired scan
        expired_scan = HistoryScan.objects.create(
            ip_hash="test_hash", consent_given=True, data_retention_until=timezone.now() - timedelta(days=1)
        )

        # Create non-consented old scan
        old_scan = HistoryScan.objects.create(consent_given=False, date=timezone.now() - timedelta(days=8))

        # Test cleanup queries
        expired_scans = GDPRComplianceService.get_scans_for_cleanup()
        self.assertIn(expired_scan, expired_scans)

        old_scans = GDPRComplianceService.get_non_consented_scans_for_deletion()
        self.assertIn(old_scan, old_scans)
