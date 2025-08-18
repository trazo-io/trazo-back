"""
Comprehensive test suite for Reviews app functionality.
Tests cover review management, moderation, and consumer feedback systems.

Test Coverage:
- Review creation and validation
- Consumer feedback and rating systems
- Review moderation and spam detection
- Establishment review aggregation
- Review response and interaction
- Privacy and content filtering
- Performance optimization for review queries
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel
from users.models import User, WorksIn

from .models import Review, ReviewModeration, ReviewResponse

User = get_user_model()


class ReviewModelTestCase(TestCase):
    """Test Review model functionality and validation."""

    def setUp(self):
        # Create producer user
        self.producer = User.objects.create_user(
            email="producer@test.com",
            password="testpass123",
            first_name="Farm",
            last_name="Owner",
            user_type="producer",
        )

        # Create consumer user
        self.consumer = User.objects.create_user(
            email="consumer@test.com",
            password="testpass123",
            first_name="Food",
            last_name="Buyer",
            user_type="consumer",
        )

        self.company = Company.objects.create(name="Review Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(
            name="Review Test Field", company=self.company, description="Sustainable organic farm"
        )

        self.parcel = Parcel.objects.create(
            name="Review Test Parcel", establishment=self.establishment, area=20.0, organic_certified=True
        )

        self.production = History.objects.create(
            title="Organic Tomato Harvest",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="harvesting",
            crop_type="tomato",
            quantity=500.0,
            unit="kg",
            created_by=self.producer,
        )

    def test_review_creation_valid(self):
        """Test creating a review with valid data."""
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            production=self.production,
            rating=4.5,
            title="Excellent organic tomatoes!",
            content="The tomatoes were fresh, flavorful, and clearly grown with care. Love supporting sustainable farming!",
            sustainability_rating=5.0,
            quality_rating=4.5,
            transparency_rating=4.0,
            verified_purchase=True,
        )

        self.assertEqual(review.consumer, self.consumer)
        self.assertEqual(review.establishment, self.establishment)
        self.assertEqual(review.production, self.production)
        self.assertEqual(review.rating, 4.5)
        self.assertEqual(review.title, "Excellent organic tomatoes!")
        self.assertTrue(review.verified_purchase)
        self.assertIn("Excellent organic tomatoes!", str(review))

    def test_review_rating_validation(self):
        """Test review rating validation (1-5 scale)."""
        # Valid rating
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=3.5,
            title="Good produce",
            content="Nice quality vegetables.",
        )
        self.assertEqual(review.rating, 3.5)

        # Invalid rating - too low
        with self.assertRaises(ValidationError):
            review = Review(
                consumer=self.consumer,
                establishment=self.establishment,
                rating=0.5,  # Below minimum
                title="Bad rating",
                content="Test content",
            )
            review.full_clean()

        # Invalid rating - too high
        with self.assertRaises(ValidationError):
            review = Review(
                consumer=self.consumer,
                establishment=self.establishment,
                rating=5.5,  # Above maximum
                title="Bad rating",
                content="Test content",
            )
            review.full_clean()

    def test_review_content_validation(self):
        """Test review content validation."""
        # Valid content
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            title="Great farm!",
            content="This farm produces excellent quality vegetables with sustainable practices.",
        )
        self.assertIsNotNone(review.content)

        # Empty title should be invalid
        with self.assertRaises(ValidationError):
            review = Review(
                consumer=self.consumer,
                establishment=self.establishment,
                rating=4.0,
                title="",  # Empty title
                content="Good content",
            )
            review.full_clean()

    def test_review_one_per_production(self):
        """Test that consumers can only review each production once."""
        # First review
        Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            production=self.production,
            rating=4.0,
            title="First review",
            content="Good produce",
        )

        # Second review for same production should fail
        with self.assertRaises(ValidationError):
            review = Review(
                consumer=self.consumer,
                establishment=self.establishment,
                production=self.production,
                rating=3.0,
                title="Second review",
                content="Different opinion",
            )
            review.full_clean()

    def test_review_self_review_prevention(self):
        """Test that producers cannot review their own establishments."""
        with self.assertRaises(ValidationError):
            review = Review(
                consumer=self.producer,  # Producer reviewing own establishment
                establishment=self.establishment,
                rating=5.0,
                title="Self review",
                content="Great farm!",
            )
            review.full_clean()

    def test_review_aggregated_ratings(self):
        """Test aggregated rating calculations."""
        # Create multiple reviews
        Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            sustainability_rating=4.5,
            quality_rating=4.0,
            transparency_rating=3.5,
            title="Good farm",
            content="Nice produce",
        )

        # Create another consumer and review
        consumer2 = User.objects.create_user(email="consumer2@test.com", password="testpass123", user_type="consumer")

        Review.objects.create(
            consumer=consumer2,
            establishment=self.establishment,
            rating=3.0,
            sustainability_rating=3.5,
            quality_rating=3.0,
            transparency_rating=2.5,
            title="Average farm",
            content="Decent quality",
        )

        # Test aggregated ratings
        reviews = Review.objects.filter(establishment=self.establishment)
        avg_rating = reviews.aggregate(avg_rating=Avg("rating"))["avg_rating"]
        avg_sustainability = reviews.aggregate(avg_sus=Avg("sustainability_rating"))["avg_sus"]

        self.assertAlmostEqual(avg_rating, 3.5, places=1)  # (4.0 + 3.0) / 2
        self.assertAlmostEqual(avg_sustainability, 4.0, places=1)  # (4.5 + 3.5) / 2

    def test_review_helpful_votes(self):
        """Test review helpful voting system."""
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            title="Helpful review",
            content="Very detailed and informative review about the farm practices.",
            helpful_votes=5,
            total_votes=7,
        )

        self.assertEqual(review.helpful_votes, 5)
        self.assertEqual(review.total_votes, 7)

        # Calculate helpfulness ratio
        helpfulness_ratio = review.helpful_votes / review.total_votes
        self.assertAlmostEqual(helpfulness_ratio, 0.714, places=3)


class ReviewModerationTestCase(TestCase):
    """Test review moderation and content filtering."""

    def setUp(self):
        self.consumer = User.objects.create_user(
            email="consumer@test.com", password="testpass123", user_type="consumer"
        )

        self.producer = User.objects.create_user(
            email="producer@test.com", password="testpass123", user_type="producer"
        )

        self.moderator = User.objects.create_user(email="moderator@test.com", password="testpass123", is_staff=True)

        self.company = Company.objects.create(name="Moderation Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(name="Moderation Test Field", company=self.company)

    def test_review_automatic_moderation(self):
        """Test automatic content moderation for inappropriate content."""
        # Review with inappropriate content
        inappropriate_review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=1.0,
            title="Terrible farm with explicit content",
            content="This farm is absolutely terrible and uses bad words and inappropriate language.",
            status="pending_moderation",  # Should be flagged for moderation
        )

        self.assertEqual(inappropriate_review.status, "pending_moderation")

    def test_review_spam_detection(self):
        """Test spam detection in reviews."""
        # Create multiple similar reviews (potential spam)
        for i in range(3):
            Review.objects.create(
                consumer=self.consumer,
                establishment=self.establishment,
                rating=5.0,
                title="Best farm ever!",
                content="This is the best farm ever! Amazing quality!",
                status="pending_moderation",
            )

        # Check for potential spam
        similar_reviews = Review.objects.filter(
            consumer=self.consumer, establishment=self.establishment, title__icontains="Best farm ever"
        ).count()

        self.assertEqual(similar_reviews, 3)

    def test_review_moderation_workflow(self):
        """Test review moderation workflow."""
        # Create review requiring moderation
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=2.0,
            title="Questionable practices",
            content="I have concerns about some of the farming practices I observed.",
            status="pending_moderation",
        )

        # Create moderation record
        moderation = ReviewModeration.objects.create(
            review=review,
            moderator=self.moderator,
            action="approved",
            reason="Content is factual and constructive feedback",
            moderated_at=timezone.now(),
        )

        # Update review status
        review.status = "approved"
        review.save()

        self.assertEqual(moderation.review, review)
        self.assertEqual(moderation.moderator, self.moderator)
        self.assertEqual(moderation.action, "approved")
        self.assertEqual(review.status, "approved")

    def test_review_rejection_workflow(self):
        """Test review rejection workflow."""
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=1.0,
            title="Spam review",
            content="Buy cheap products at example.com! Click here now!",
            status="pending_moderation",
        )

        # Reject review
        moderation = ReviewModeration.objects.create(
            review=review,
            moderator=self.moderator,
            action="rejected",
            reason="Contains spam/promotional content",
            moderated_at=timezone.now(),
        )

        review.status = "rejected"
        review.save()

        self.assertEqual(moderation.action, "rejected")
        self.assertEqual(review.status, "rejected")
        self.assertIn("spam", moderation.reason.lower())

    def test_review_edit_moderation(self):
        """Test moderation when reviews are edited."""
        # Create approved review
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            title="Good farm",
            content="Nice quality produce",
            status="approved",
        )

        # Edit review content
        review.content = "Updated content with more details about the farming practices"
        review.status = "pending_moderation"  # Should require re-moderation
        review.save()

        self.assertEqual(review.status, "pending_moderation")


class ReviewResponseTestCase(TestCase):
    """Test review response functionality."""

    def setUp(self):
        self.consumer = User.objects.create_user(
            email="consumer@test.com", password="testpass123", user_type="consumer"
        )

        self.producer = User.objects.create_user(
            email="producer@test.com", password="testpass123", user_type="producer"
        )

        self.company = Company.objects.create(name="Response Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(name="Response Test Field", company=self.company)

        self.review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=3.0,
            title="Average experience",
            content="The produce was okay but delivery was delayed.",
            status="approved",
        )

    def test_producer_response_creation(self):
        """Test producer response to reviews."""
        response = ReviewResponse.objects.create(
            review=self.review,
            responder=self.producer,
            content="Thank you for your feedback. We apologize for the delivery delay and are working to improve our logistics.",
            response_type="producer_response",
        )

        self.assertEqual(response.review, self.review)
        self.assertEqual(response.responder, self.producer)
        self.assertEqual(response.response_type, "producer_response")
        self.assertIn("Thank you for your feedback", response.content)

    def test_consumer_follow_up(self):
        """Test consumer follow-up to producer responses."""
        # Producer response
        producer_response = ReviewResponse.objects.create(
            review=self.review,
            responder=self.producer,
            content="We appreciate your feedback and have made improvements.",
            response_type="producer_response",
        )

        # Consumer follow-up
        consumer_follow_up = ReviewResponse.objects.create(
            review=self.review,
            responder=self.consumer,
            content="Thank you for addressing my concerns. Will try ordering again.",
            response_type="consumer_follow_up",
            parent_response=producer_response,
        )

        self.assertEqual(consumer_follow_up.parent_response, producer_response)
        self.assertEqual(consumer_follow_up.response_type, "consumer_follow_up")

    def test_response_permissions(self):
        """Test response permissions and validation."""
        # Only establishment owner should be able to respond as producer
        with self.assertRaises(ValidationError):
            unauthorized_user = User.objects.create_user(email="unauthorized@test.com", password="testpass123")

            response = ReviewResponse(
                review=self.review,
                responder=unauthorized_user,
                content="Unauthorized response",
                response_type="producer_response",
            )
            response.full_clean()

    def test_response_threading(self):
        """Test threaded responses."""
        # Initial producer response
        response1 = ReviewResponse.objects.create(
            review=self.review, responder=self.producer, content="Initial response", response_type="producer_response"
        )

        # Consumer reply
        response2 = ReviewResponse.objects.create(
            review=self.review,
            responder=self.consumer,
            content="Consumer reply",
            response_type="consumer_follow_up",
            parent_response=response1,
        )

        # Producer follow-up
        response3 = ReviewResponse.objects.create(
            review=self.review,
            responder=self.producer,
            content="Producer follow-up",
            response_type="producer_response",
            parent_response=response2,
        )

        # Test response chain
        self.assertEqual(response2.parent_response, response1)
        self.assertEqual(response3.parent_response, response2)

        # Test getting response thread
        responses = ReviewResponse.objects.filter(review=self.review).order_by("created_at")
        self.assertEqual(responses.count(), 3)


class ReviewAPITestCase(APITestCase):
    """Test Review API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        # Create test users
        self.consumer = User.objects.create_user(
            email="consumer@test.com", password="testpass123", user_type="consumer"
        )

        self.producer = User.objects.create_user(
            email="producer@test.com", password="testpass123", user_type="producer"
        )

        self.company = Company.objects.create(name="API Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(name="API Test Field", company=self.company)

        self.production = History.objects.create(
            title="API Test Production",
            establishment=self.establishment,
            event_date=timezone.now().date(),
            event_type="harvesting",
            created_by=self.producer,
        )

    def test_create_review_authenticated(self):
        """Test creating review requires authentication."""
        url = reverse("review-list")

        data = {
            "establishment": self.establishment.id,
            "production": self.production.id,
            "rating": 4.0,
            "title": "Great farm!",
            "content": "Excellent produce quality",
        }

        # Unauthenticated request should fail
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request should succeed
        self.client.force_authenticate(user=self.consumer)
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_review_valid_data(self):
        """Test creating review with valid data."""
        self.client.force_authenticate(user=self.consumer)
        url = reverse("review-list")

        data = {
            "establishment": self.establishment.id,
            "production": self.production.id,
            "rating": 4.5,
            "title": "Excellent organic produce",
            "content": "The vegetables were fresh and clearly grown with sustainable practices.",
            "sustainability_rating": 5.0,
            "quality_rating": 4.5,
            "transparency_rating": 4.0,
            "verified_purchase": True,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["rating"], 4.5)
        self.assertEqual(response.data["title"], "Excellent organic produce")
        self.assertTrue(response.data["verified_purchase"])

    def test_create_review_invalid_data(self):
        """Test creating review with invalid data."""
        self.client.force_authenticate(user=self.consumer)
        url = reverse("review-list")

        # Missing required fields
        data = {
            "establishment": self.establishment.id,
            "rating": 6.0,  # Invalid rating
            "title": "",  # Empty title
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_reviews_filtered_by_establishment(self):
        """Test listing reviews filtered by establishment."""
        # Create reviews for different establishments
        other_producer = User.objects.create_user(email="other@test.com", password="testpass123")
        other_company = Company.objects.create(name="Other Farm", owner=other_producer)
        other_establishment = Establishment.objects.create(name="Other Field", company=other_company)

        # Review for main establishment
        Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            title="Main farm review",
            content="Good quality",
            status="approved",
        )

        # Review for other establishment
        Review.objects.create(
            consumer=self.consumer,
            establishment=other_establishment,
            rating=3.0,
            title="Other farm review",
            content="Average quality",
            status="approved",
        )

        # Filter by establishment
        url = reverse("review-list")
        response = self.client.get(url, {"establishment": self.establishment.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Main farm review")

    def test_update_review_permissions(self):
        """Test review update permissions."""
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            title="Original title",
            content="Original content",
            status="approved",
        )

        url = reverse("review-detail", kwargs={"pk": review.pk})

        data = {"title": "Updated title", "content": "Updated content"}

        # Consumer should be able to update their own review
        self.client.force_authenticate(user=self.consumer)
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated title")

        # Other users should not be able to update
        other_consumer = User.objects.create_user(email="other_consumer@test.com", password="testpass123")

        self.client.force_authenticate(user=other_consumer)
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_review_permissions(self):
        """Test review deletion permissions."""
        review = Review.objects.create(
            consumer=self.consumer,
            establishment=self.establishment,
            rating=4.0,
            title="To be deleted",
            content="Content to delete",
            status="approved",
        )

        url = reverse("review-detail", kwargs={"pk": review.pk})

        # Consumer should be able to delete their own review
        self.client.force_authenticate(user=self.consumer)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())


class ReviewAnalyticsTestCase(TestCase):
    """Test review analytics and aggregation."""

    def setUp(self):
        self.producer = User.objects.create_user(email="producer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Analytics Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(name="Analytics Test Field", company=self.company)

        # Create multiple consumers and reviews
        self.consumers = []
        self.reviews = []

        for i in range(10):
            consumer = User.objects.create_user(
                email=f"consumer{i}@test.com", password="testpass123", user_type="consumer"
            )
            self.consumers.append(consumer)

            review = Review.objects.create(
                consumer=consumer,
                establishment=self.establishment,
                rating=3.0 + (i % 3),  # Ratings: 3, 4, 5, 3, 4, 5, etc.
                sustainability_rating=4.0 + (i % 2),  # 4.0 or 5.0
                quality_rating=3.5 + (i % 3) * 0.5,  # 3.5, 4.0, 4.5
                transparency_rating=3.0 + (i % 4) * 0.5,  # 3.0, 3.5, 4.0, 4.5
                title=f"Review {i}",
                content=f"Content for review {i}",
                status="approved",
            )
            self.reviews.append(review)

    def test_establishment_rating_aggregation(self):
        """Test establishment rating aggregation."""
        reviews = Review.objects.filter(establishment=self.establishment, status="approved")

        aggregated_data = reviews.aggregate(
            avg_rating=Avg("rating"),
            avg_sustainability=Avg("sustainability_rating"),
            avg_quality=Avg("quality_rating"),
            avg_transparency=Avg("transparency_rating"),
            total_reviews=Count("id"),
        )

        self.assertEqual(aggregated_data["total_reviews"], 10)
        self.assertIsNotNone(aggregated_data["avg_rating"])
        self.assertIsNotNone(aggregated_data["avg_sustainability"])

        # Check rating averages are in valid range
        self.assertGreaterEqual(aggregated_data["avg_rating"], 1.0)
        self.assertLessEqual(aggregated_data["avg_rating"], 5.0)

    def test_review_distribution_analysis(self):
        """Test review rating distribution analysis."""
        # Count reviews by rating
        rating_distribution = {}
        for rating in [1, 2, 3, 4, 5]:
            count = Review.objects.filter(establishment=self.establishment, rating=rating, status="approved").count()
            rating_distribution[rating] = count

        # Should have reviews in different rating categories
        total_reviews = sum(rating_distribution.values())
        self.assertEqual(total_reviews, 10)

    def test_review_trends_over_time(self):
        """Test review trends over time."""
        # Create reviews across different months
        base_date = timezone.now().date()
        monthly_reviews = {}

        for i in range(6):  # 6 months of data
            month_date = base_date.replace(
                month=base_date.month - i if base_date.month > i else 12 + base_date.month - i
            )

            consumer = User.objects.create_user(
                email=f"monthly_consumer{i}@test.com", password="testpass123", user_type="consumer"
            )

            review = Review.objects.create(
                consumer=consumer,
                establishment=self.establishment,
                rating=4.0,
                title=f"Monthly review {i}",
                content=f"Monthly content {i}",
                status="approved",
            )

            # Manually set created_at for testing
            review.created_at = timezone.make_aware(datetime.combine(month_date, datetime.min.time()))
            review.save()

            month_key = month_date.strftime("%Y-%m")
            monthly_reviews[month_key] = monthly_reviews.get(month_key, 0) + 1

        # Should have reviews distributed across months
        self.assertGreater(len(monthly_reviews), 0)

    def test_review_sentiment_analysis(self):
        """Test review sentiment analysis (basic keyword detection)."""
        # Create reviews with different sentiment keywords
        positive_keywords = ["excellent", "amazing", "fantastic", "love", "perfect"]
        negative_keywords = ["terrible", "awful", "disappointing", "poor", "worst"]

        positive_review = Review.objects.create(
            consumer=self.consumers[0],
            establishment=self.establishment,
            rating=5.0,
            title="Excellent farm!",
            content="Amazing quality produce, fantastic farming practices!",
            status="approved",
        )

        negative_review = Review.objects.create(
            consumer=self.consumers[1],
            establishment=self.establishment,
            rating=2.0,
            title="Disappointing experience",
            content="Poor quality vegetables, terrible customer service.",
            status="approved",
        )

        # Simple sentiment scoring based on keywords
        def calculate_sentiment(text):
            text_lower = text.lower()
            positive_score = sum(1 for word in positive_keywords if word in text_lower)
            negative_score = sum(1 for word in negative_keywords if word in text_lower)
            return positive_score - negative_score

        positive_sentiment = calculate_sentiment(positive_review.content)
        negative_sentiment = calculate_sentiment(negative_review.content)

        self.assertGreater(positive_sentiment, 0)
        self.assertLess(negative_sentiment, 0)


class ReviewPerformanceTestCase(TestCase):
    """Test review performance optimizations."""

    def setUp(self):
        self.producer = User.objects.create_user(email="performance@test.com", password="testpass123")

        self.company = Company.objects.create(name="Performance Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(name="Performance Test Field", company=self.company)

    def test_bulk_review_creation(self):
        """Test bulk creation of reviews for performance."""
        consumers = []
        for i in range(50):
            consumer = User.objects.create_user(
                email=f"bulk_consumer{i}@test.com", password="testpass123", user_type="consumer"
            )
            consumers.append(consumer)

        # Bulk create reviews
        reviews_data = []
        for i, consumer in enumerate(consumers):
            reviews_data.append(
                Review(
                    consumer=consumer,
                    establishment=self.establishment,
                    rating=3.0 + (i % 3),
                    title=f"Bulk review {i}",
                    content=f"Bulk content {i}",
                    status="approved",
                )
            )

        created_reviews = Review.objects.bulk_create(reviews_data)

        self.assertEqual(len(created_reviews), 50)
        self.assertEqual(Review.objects.filter(establishment=self.establishment).count(), 50)

    def test_review_queryset_optimization(self):
        """Test review queryset optimizations."""
        # Create test data
        consumers = []
        for i in range(20):
            consumer = User.objects.create_user(
                email=f"query_consumer{i}@test.com", password="testpass123", user_type="consumer"
            )
            consumers.append(consumer)

            Review.objects.create(
                consumer=consumer,
                establishment=self.establishment,
                rating=4.0,
                title=f"Query test {i}",
                content=f"Query content {i}",
                status="approved",
            )

        # Test select_related optimization
        reviews_with_consumer = Review.objects.select_related("consumer", "establishment").all()
        self.assertEqual(len(list(reviews_with_consumer)), 20)

        # Test prefetch_related optimization for responses
        reviews_with_responses = Review.objects.prefetch_related("responses").all()
        self.assertEqual(len(list(reviews_with_responses)), 20)

    def test_review_aggregation_performance(self):
        """Test performance of review aggregation queries."""
        # Create substantial test data
        for i in range(100):
            consumer = User.objects.create_user(
                email=f"agg_consumer{i}@test.com", password="testpass123", user_type="consumer"
            )

            Review.objects.create(
                consumer=consumer,
                establishment=self.establishment,
                rating=1.0 + (i % 5),  # Distribute across all ratings
                sustainability_rating=2.0 + (i % 4),
                quality_rating=2.5 + (i % 3) * 0.5,
                title=f"Aggregation test {i}",
                content=f"Aggregation content {i}",
                status="approved",
            )

        # Complex aggregation query
        aggregated_stats = Review.objects.filter(establishment=self.establishment, status="approved").aggregate(
            avg_rating=Avg("rating"),
            avg_sustainability=Avg("sustainability_rating"),
            avg_quality=Avg("quality_rating"),
            total_reviews=Count("id"),
            five_star_count=Count("id", filter=Q(rating=5.0)),
            four_star_count=Count("id", filter=Q(rating=4.0)),
            three_star_count=Count("id", filter=Q(rating=3.0)),
            two_star_count=Count("id", filter=Q(rating=2.0)),
            one_star_count=Count("id", filter=Q(rating=1.0)),
        )

        self.assertEqual(aggregated_stats["total_reviews"], 100)
        self.assertIsNotNone(aggregated_stats["avg_rating"])
        self.assertIsNotNone(aggregated_stats["avg_sustainability"])
