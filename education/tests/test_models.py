"""Tests for the education app's served surface: the farmer FAQ.

This file used to carry ~1,000 lines covering the category/course/lesson
catalogue, progress tracking, certificates, bookmarks and their API. That
surface was removed 2026-08-24 (nothing rendered it — the topic pages are
i18n strings in the app bundle; only the FAQ endpoint is consumed), and its
tests had already rotted against the real models (string ``user_type``,
missing ``estimated_duration``, ``__str__`` on a username that is None):
14 errors and 1 failure on every run. The retired models remain for their
migrations only and are exercised by the seeder purge test in
``test_seed_education_content``.
"""

from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from education.models import FarmerQuestionAnswer
from users.models import User


class FarmerQuestionAnswerTestCase(TestCase):
    """Test FAQ model functionality."""

    def test_faq_creation(self):
        """Test creating FAQ entry."""
        faq = FarmerQuestionAnswer.objects.create(
            question="How do I log an activity?",
            answer="From your parcel or the Activities page, press Add event.",
            category="quick_add",
            is_featured=True,
            view_count=0,
            helpful_votes=0,
        )

        self.assertIn("log an activity", faq.question)
        self.assertEqual(faq.category, "quick_add")
        self.assertTrue(faq.is_featured)
        self.assertEqual(faq.view_count, 0)
        self.assertIn("How do I log", str(faq))

    def test_faq_popularity_tracking(self):
        """Test FAQ view count and helpful votes."""
        faq = FarmerQuestionAnswer.objects.create(
            question="How do I add photos to an activity?",
            answer="The photo step is the last step of every activity form.",
            category="quick_add",
            view_count=150,
            helpful_votes=45,
        )

        faq.view_count += 10
        faq.save()
        faq.helpful_votes += 5
        faq.save()

        self.assertEqual(faq.view_count, 160)
        self.assertEqual(faq.helpful_votes, 50)


class FarmerQuestionAnswerAPITestCase(APITestCase):
    """The FAQ endpoint is the education app's only API surface."""

    def setUp(self):
        self.user = User.objects.create_user(email="grower@test.com", password="testpass123")
        self.client = APIClient()
        self.featured = FarmerQuestionAnswer.objects.create(
            question="What deadlines matter for renewal season?",
            answer="October to April, depending on your certifier.",
            category="osp_renewal",
            is_featured=True,
            helpful_votes=10,
        )
        self.plain = FarmerQuestionAnswer.objects.create(
            question="Can I use voice to log faster?",
            answer="Yes — inside the activity form.",
            category="quick_add",
            is_featured=False,
            helpful_votes=2,
        )

    def test_requires_authentication(self):
        response = self.client.get("/api/education/faqs/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_list_orders_featured_first(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/education/faqs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        questions = [row["question"] for row in response.json()]
        self.assertEqual(questions[0], self.featured.question)
        self.assertIn(self.plain.question, questions)

    def test_featured_action(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/education/faqs/featured/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        questions = [row["question"] for row in response.json()]
        self.assertEqual(questions, [self.featured.question])

    def test_mark_helpful_increments(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/education/faqs/{self.plain.pk}/mark_helpful/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.helpful_votes, 3)

    def test_retrieve_increments_view_count(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/education/faqs/{self.plain.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.view_count, 1)
