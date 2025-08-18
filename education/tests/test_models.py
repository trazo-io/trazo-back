"""
Comprehensive test suite for Education app functionality.
Tests cover content management, user progress tracking, and farmer education features.

Test Coverage:
- Educational content creation and validation
- Course and lesson management
- User progress tracking and analytics
- Certification issuance and validation
- FAQ and knowledge base functionality
- Content accessibility and permissions
- Performance optimizations for large datasets
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
from subscriptions.models import Subscription
from users.models import User, WorksIn

from .models import (
    EducationBookmark,
    EducationCategory,
    EducationCertificate,
    EducationCourse,
    EducationLesson,
    FarmerQuestionAnswer,
    UserEducationProgress,
)

User = get_user_model()


class EducationCategoryTestCase(TestCase):
    """Test EducationCategory model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(email="admin@test.com", password="testpass123", is_staff=True)

    def test_category_creation_valid(self):
        """Test creating education category with valid data."""
        category = EducationCategory.objects.create(
            name="Getting Started with Trazo",
            category_type="getting_started",
            description="Learn the basics of using Trazo for your farm operations",
            icon="fas fa-seedling",
            order=1,
            is_active=True,
        )

        self.assertEqual(category.name, "Getting Started with Trazo")
        self.assertEqual(category.category_type, "getting_started")
        self.assertEqual(category.icon, "fas fa-seedling")
        self.assertTrue(category.is_active)
        self.assertIn("Getting Started", str(category))

    def test_category_type_uniqueness(self):
        """Test that category types are unique."""
        EducationCategory.objects.create(
            name="Carbon Tracking Basics",
            category_type="carbon_tracking",
            description="Learn carbon footprint tracking",
        )

        # Creating another category with same type should fail
        with self.assertRaises(Exception):
            EducationCategory.objects.create(
                name="Advanced Carbon Tracking",
                category_type="carbon_tracking",  # Duplicate type
                description="Advanced carbon tracking techniques",
            )

    def test_category_ordering(self):
        """Test category ordering by order field."""
        category1 = EducationCategory.objects.create(
            name="Third Category", category_type="sustainability", description="Test", order=3
        )

        category2 = EducationCategory.objects.create(
            name="First Category", category_type="getting_started", description="Test", order=1
        )

        category3 = EducationCategory.objects.create(
            name="Second Category", category_type="carbon_tracking", description="Test", order=2
        )

        categories = EducationCategory.objects.all()
        self.assertEqual(categories[0], category2)  # order=1
        self.assertEqual(categories[1], category3)  # order=2
        self.assertEqual(categories[2], category1)  # order=3

    def test_category_activation_toggle(self):
        """Test category activation/deactivation."""
        category = EducationCategory.objects.create(
            name="Test Category", category_type="iot_automation", description="Test category", is_active=True
        )

        self.assertTrue(category.is_active)

        # Deactivate category
        category.is_active = False
        category.save()

        self.assertFalse(category.is_active)


class EducationCourseTestCase(TestCase):
    """Test EducationCourse model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(email="educator@test.com", password="testpass123")

        self.category = EducationCategory.objects.create(
            name="Carbon Tracking", category_type="carbon_tracking", description="Learn carbon footprint tracking"
        )

    def test_course_creation_valid(self):
        """Test creating course with valid data."""
        course = EducationCourse.objects.create(
            title="Introduction to Carbon Footprint Tracking",
            category=self.category,
            description="Learn how to track your farm's carbon footprint using Trazo",
            difficulty="beginner",
            required_plan="all",
            estimated_duration=45,
            order=1,
            is_featured=True,
            target_crops="corn,wheat,soybeans",
            farm_size_min=10,
            farm_size_max=500,
        )

        self.assertEqual(course.title, "Introduction to Carbon Footprint Tracking")
        self.assertEqual(course.category, self.category)
        self.assertEqual(course.difficulty, "beginner")
        self.assertEqual(course.estimated_duration, 45)
        self.assertTrue(course.is_featured)
        self.assertEqual(course.farm_size_min, 10)
        self.assertIn("beginner", str(course))

    def test_course_target_crops_filtering(self):
        """Test filtering courses by target crops."""
        corn_course = EducationCourse.objects.create(
            title="Corn Farming with Trazo",
            category=self.category,
            description="Corn-specific guidance",
            difficulty="intermediate",
            target_crops="corn",
        )

        wheat_course = EducationCourse.objects.create(
            title="Wheat Production Tracking",
            category=self.category,
            description="Wheat-specific guidance",
            difficulty="intermediate",
            target_crops="wheat,barley",
        )

        # Filter courses for corn farmers
        corn_courses = EducationCourse.objects.filter(target_crops__icontains="corn")

        self.assertIn(corn_course, corn_courses)
        self.assertNotIn(wheat_course, corn_courses)

    def test_course_farm_size_filtering(self):
        """Test filtering courses by farm size."""
        small_farm_course = EducationCourse.objects.create(
            title="Small Farm Operations",
            category=self.category,
            description="For smaller farms",
            difficulty="beginner",
            farm_size_min=1,
            farm_size_max=50,
        )

        large_farm_course = EducationCourse.objects.create(
            title="Enterprise Farm Management",
            category=self.category,
            description="For larger operations",
            difficulty="advanced",
            farm_size_min=100,
            farm_size_max=1000,
        )

        # Filter for medium-sized farm (75 acres)
        suitable_courses = EducationCourse.objects.filter(
            Q(farm_size_min__lte=75, farm_size_max__gte=75) | Q(farm_size_min__isnull=True, farm_size_max__isnull=True)
        )

        # Only small farm course should be suitable
        self.assertNotIn(small_farm_course, suitable_courses)  # Too small max
        self.assertNotIn(large_farm_course, suitable_courses)  # Too large min

    def test_course_plan_access_validation(self):
        """Test course access based on subscription plan."""
        basic_course = EducationCourse.objects.create(
            title="Basic Course",
            category=self.category,
            description="Available to all",
            difficulty="beginner",
            required_plan="basic",
        )

        corporate_course = EducationCourse.objects.create(
            title="Enterprise Features",
            category=self.category,
            description="Corporate only",
            difficulty="advanced",
            required_plan="corporate",
        )

        self.assertEqual(basic_course.required_plan, "basic")
        self.assertEqual(corporate_course.required_plan, "corporate")


class EducationLessonTestCase(TestCase):
    """Test EducationLesson model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(email="educator@test.com", password="testpass123")

        self.category = EducationCategory.objects.create(
            name="IoT Automation", category_type="iot_automation", description="Learn IoT integration"
        )

        self.course = EducationCourse.objects.create(
            title="IoT Sensors for Farms",
            category=self.category,
            description="Learn to use IoT sensors",
            difficulty="intermediate",
            estimated_duration=60,
        )

    def test_lesson_creation_valid(self):
        """Test creating lesson with valid data."""
        lesson = EducationLesson.objects.create(
            course=self.course,
            title="Setting Up Soil Moisture Sensors",
            content_type="video",
            content="""
            # Setting Up Soil Moisture Sensors
            
            In this lesson, you'll learn how to install and configure soil moisture sensors
            that integrate with Trazo's IoT platform.
            
            ## Required Equipment
            - Soil moisture sensor
            - LoRaWAN gateway
            - Mobile app
            
            ## Installation Steps
            1. Choose sensor location
            2. Install sensor at proper depth
            3. Configure in Trazo app
            """,
            video_url="https://youtube.com/watch?v=example",
            duration=15,
            order=1,
            has_quiz=True,
            quiz_questions={
                "questions": [
                    {
                        "question": "What depth should soil sensors be installed?",
                        "options": ["2 inches", "6 inches", "12 inches", "18 inches"],
                        "correct": 2,
                    }
                ]
            },
            practical_steps=[
                "Purchase compatible soil sensor",
                "Download Trazo mobile app",
                "Follow installation guide",
                "Test sensor readings",
            ],
            real_farm_example="Johnson Family Farm reduced irrigation costs by 30% using these sensors",
            cost_savings_potential="$200-500 annually",
            time_savings_potential="5 hours per week",
        )

        self.assertEqual(lesson.course, self.course)
        self.assertEqual(lesson.title, "Setting Up Soil Moisture Sensors")
        self.assertEqual(lesson.content_type, "video")
        self.assertEqual(lesson.duration, 15)
        self.assertTrue(lesson.has_quiz)
        self.assertEqual(len(lesson.practical_steps), 4)
        self.assertIn("Johnson Family Farm", lesson.real_farm_example)
        self.assertIn("IoT Sensors for Farms", str(lesson))

    def test_lesson_content_types(self):
        """Test different lesson content types."""
        content_types = ["text", "video", "interactive", "checklist", "case_study"]

        for i, content_type in enumerate(content_types):
            lesson = EducationLesson.objects.create(
                course=self.course,
                title=f"Test {content_type} Lesson",
                content_type=content_type,
                content=f"Content for {content_type} lesson",
                duration=10,
                order=i + 1,
            )

            self.assertEqual(lesson.content_type, content_type)

    def test_lesson_quiz_functionality(self):
        """Test lesson quiz questions and scoring."""
        lesson = EducationLesson.objects.create(
            course=self.course,
            title="Quiz Lesson",
            content_type="interactive",
            content="Interactive lesson with quiz",
            duration=20,
            has_quiz=True,
            quiz_questions={
                "questions": [
                    {
                        "question": "What is the main benefit of IoT sensors?",
                        "options": ["Cost reduction", "Data collection", "Automation", "All of the above"],
                        "correct": 3,
                    },
                    {
                        "question": "How often should sensors be calibrated?",
                        "options": ["Weekly", "Monthly", "Seasonally", "Annually"],
                        "correct": 2,
                    },
                ]
            },
        )

        self.assertTrue(lesson.has_quiz)
        self.assertEqual(len(lesson.quiz_questions["questions"]), 2)
        self.assertEqual(lesson.quiz_questions["questions"][0]["correct"], 3)

    def test_lesson_practical_steps(self):
        """Test practical action steps for farmers."""
        lesson = EducationLesson.objects.create(
            course=self.course,
            title="Practical Implementation",
            content_type="checklist",
            content="Step-by-step implementation guide",
            duration=30,
            practical_steps=[
                "Assess current irrigation system",
                "Identify sensor placement locations",
                "Purchase recommended sensors",
                "Install sensors following guide",
                "Configure Trazo integration",
                "Monitor and adjust settings",
            ],
        )

        self.assertEqual(len(lesson.practical_steps), 6)
        self.assertIn("Assess current irrigation", lesson.practical_steps[0])


class UserEducationProgressTestCase(TestCase):
    """Test user progress tracking functionality."""

    def setUp(self):
        self.farmer = User.objects.create_user(email="farmer@test.com", password="testpass123", user_type="producer")

        self.category = EducationCategory.objects.create(
            name="Carbon Tracking", category_type="carbon_tracking", description="Learn carbon tracking"
        )

        self.course = EducationCourse.objects.create(
            title="Carbon Footprint Basics",
            category=self.category,
            description="Basic carbon tracking",
            difficulty="beginner",
            estimated_duration=60,
        )

        self.lesson = EducationLesson.objects.create(
            course=self.course,
            title="Understanding Carbon Emissions",
            content_type="text",
            content="Learn about carbon emissions",
            duration=20,
            has_quiz=True,
        )

    def test_progress_creation(self):
        """Test creating user progress record."""
        progress = UserEducationProgress.objects.create(
            user=self.farmer,
            lesson=self.lesson,
            quiz_score=85,
            time_spent=22,
            bookmarked=True,
            helpful_rating=4,
            feedback="Very helpful lesson, practical examples were great",
        )

        self.assertEqual(progress.user, self.farmer)
        self.assertEqual(progress.lesson, self.lesson)
        self.assertEqual(progress.quiz_score, 85)
        self.assertEqual(progress.time_spent, 22)
        self.assertTrue(progress.bookmarked)
        self.assertEqual(progress.helpful_rating, 4)
        self.assertFalse(progress.is_completed)  # Not completed until completed_at is set

    def test_lesson_completion(self):
        """Test marking lesson as completed."""
        progress = UserEducationProgress.objects.create(user=self.farmer, lesson=self.lesson, time_spent=20)

        # Mark as completed
        progress.completed_at = timezone.now()
        progress.save()

        self.assertTrue(progress.is_completed)
        self.assertIsNotNone(progress.completed_at)

    def test_unique_progress_per_lesson(self):
        """Test that each user can have only one progress record per lesson."""
        UserEducationProgress.objects.create(user=self.farmer, lesson=self.lesson, time_spent=10)

        # Creating another progress for same user/lesson should fail
        with self.assertRaises(Exception):
            UserEducationProgress.objects.create(
                user=self.farmer, lesson=self.lesson, time_spent=20  # Duplicate user/lesson combination
            )

    def test_progress_analytics(self):
        """Test progress analytics calculations."""
        # Create multiple progress records
        lessons = []
        for i in range(5):
            lesson = EducationLesson.objects.create(
                course=self.course,
                title=f"Lesson {i+1}",
                content_type="text",
                content=f"Content {i+1}",
                duration=15,
                order=i + 1,
            )
            lessons.append(lesson)

            UserEducationProgress.objects.create(
                user=self.farmer,
                lesson=lesson,
                quiz_score=70 + (i * 5),  # 70, 75, 80, 85, 90
                time_spent=15 + i,  # 15, 16, 17, 18, 19
                completed_at=timezone.now() if i < 3 else None,  # 3 completed
                helpful_rating=3 + (i % 3),  # 3, 4, 5, 3, 4
            )

        # Calculate analytics
        progress_records = UserEducationProgress.objects.filter(user=self.farmer)

        avg_quiz_score = progress_records.aggregate(avg_score=Avg("quiz_score"))["avg_score"]
        total_time = sum(p.time_spent for p in progress_records)
        completed_count = progress_records.filter(completed_at__isnull=False).count()
        avg_rating = progress_records.aggregate(avg_rating=Avg("helpful_rating"))["avg_rating"]

        self.assertEqual(avg_quiz_score, 80.0)  # (70+75+80+85+90)/5
        self.assertEqual(total_time, 85)  # 15+16+17+18+19
        self.assertEqual(completed_count, 3)
        self.assertEqual(avg_rating, 3.6)  # (3+4+5+3+4)/5


class EducationCertificateTestCase(TestCase):
    """Test education certificate functionality."""

    def setUp(self):
        self.farmer = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.category = EducationCategory.objects.create(
            name="Sustainability", category_type="sustainability", description="Sustainable practices"
        )

        self.course = EducationCourse.objects.create(
            title="Sustainable Farming Practices",
            category=self.category,
            description="Learn sustainable farming",
            difficulty="intermediate",
            estimated_duration=120,
        )

    def test_certificate_creation(self):
        """Test creating education certificate."""
        certificate = EducationCertificate.objects.create(
            user=self.farmer,
            course=self.course,
            certificate_id="TRAZO-CERT-2024-001",
            completion_percentage=95,
            total_time_spent=125,
            average_quiz_score=88,
        )

        self.assertEqual(certificate.user, self.farmer)
        self.assertEqual(certificate.course, self.course)
        self.assertEqual(certificate.certificate_id, "TRAZO-CERT-2024-001")
        self.assertEqual(certificate.completion_percentage, 95)
        self.assertEqual(certificate.total_time_spent, 125)
        self.assertEqual(certificate.average_quiz_score, 88)
        self.assertIn("TRAZO-CERT-2024-001", str(certificate))

    def test_certificate_uniqueness(self):
        """Test that users can have only one certificate per course."""
        EducationCertificate.objects.create(
            user=self.farmer,
            course=self.course,
            certificate_id="CERT-001",
            completion_percentage=90,
            total_time_spent=110,
        )

        # Creating another certificate for same user/course should fail
        with self.assertRaises(Exception):
            EducationCertificate.objects.create(
                user=self.farmer,
                course=self.course,  # Duplicate user/course
                certificate_id="CERT-002",
                completion_percentage=95,
                total_time_spent=120,
            )

    def test_certificate_id_uniqueness(self):
        """Test that certificate IDs are unique."""
        EducationCertificate.objects.create(
            user=self.farmer,
            course=self.course,
            certificate_id="UNIQUE-CERT-001",
            completion_percentage=90,
            total_time_spent=110,
        )

        # Create another user and course
        other_user = User.objects.create_user(email="other@test.com", password="testpass123")

        other_course = EducationCourse.objects.create(
            title="Other Course",
            category=self.category,
            description="Different course",
            difficulty="beginner",
            estimated_duration=60,
        )

        # Using same certificate ID should fail
        with self.assertRaises(Exception):
            EducationCertificate.objects.create(
                user=other_user,
                course=other_course,
                certificate_id="UNIQUE-CERT-001",  # Duplicate ID
                completion_percentage=85,
                total_time_spent=55,
            )


class EducationBookmarkTestCase(TestCase):
    """Test education bookmark functionality."""

    def setUp(self):
        self.farmer = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.category = EducationCategory.objects.create(
            name="Technical Support", category_type="troubleshooting", description="Technical help"
        )

        self.course = EducationCourse.objects.create(
            title="Troubleshooting IoT Devices",
            category=self.category,
            description="Fix common issues",
            difficulty="intermediate",
            estimated_duration=45,
        )

        self.lesson = EducationLesson.objects.create(
            course=self.course,
            title="Sensor Connectivity Issues",
            content_type="checklist",
            content="Troubleshooting steps",
            duration=15,
        )

    def test_bookmark_creation(self):
        """Test creating bookmark with notes."""
        bookmark = EducationBookmark.objects.create(
            user=self.farmer,
            lesson=self.lesson,
            notes="Need to remember this for my field sensors - very useful troubleshooting steps",
        )

        self.assertEqual(bookmark.user, self.farmer)
        self.assertEqual(bookmark.lesson, self.lesson)
        self.assertIn("troubleshooting steps", bookmark.notes)
        self.assertIn("Sensor Connectivity", str(bookmark))

    def test_bookmark_uniqueness(self):
        """Test that users can bookmark each lesson only once."""
        EducationBookmark.objects.create(user=self.farmer, lesson=self.lesson, notes="First bookmark")

        # Creating another bookmark for same user/lesson should fail
        with self.assertRaises(Exception):
            EducationBookmark.objects.create(
                user=self.farmer, lesson=self.lesson, notes="Second bookmark"  # Duplicate user/lesson
            )

    def test_bookmark_without_notes(self):
        """Test creating bookmark without notes."""
        bookmark = EducationBookmark.objects.create(user=self.farmer, lesson=self.lesson)

        self.assertEqual(bookmark.notes, "")
        self.assertIsNotNone(bookmark.created_at)


class FarmerQuestionAnswerTestCase(TestCase):
    """Test FAQ functionality."""

    def setUp(self):
        self.staff_user = User.objects.create_user(email="support@test.com", password="testpass123", is_staff=True)

    def test_faq_creation(self):
        """Test creating FAQ entry."""
        faq = FarmerQuestionAnswer.objects.create(
            question="How do I connect my John Deere tractor to Trazo?",
            answer="""
            To connect your John Deere tractor to Trazo:
            
            1. Ensure your tractor has MyJohnDeere connectivity
            2. Create a MyJohnDeere account
            3. In Trazo, go to Settings > IoT Integrations
            4. Select "John Deere" and follow authentication steps
            5. Grant permissions for field operations data
            6. Your tractor data will sync automatically
            """,
            category="iot",
            is_featured=True,
            view_count=0,
            helpful_votes=0,
        )

        self.assertIn("John Deere tractor", faq.question)
        self.assertIn("MyJohnDeere connectivity", faq.answer)
        self.assertEqual(faq.category, "iot")
        self.assertTrue(faq.is_featured)
        self.assertEqual(faq.view_count, 0)
        self.assertIn("How do I connect", str(faq))

    def test_faq_categories(self):
        """Test different FAQ categories."""
        categories = [
            ("setup", "How do I create my first farm?"),
            ("data_entry", "How do I log fertilizer applications?"),
            ("carbon", "How is my carbon footprint calculated?"),
            ("iot", "Which sensors are compatible?"),
            ("qr_codes", "How do consumers scan QR codes?"),
            ("billing", "How do I upgrade my plan?"),
            ("technical", "Why is the app running slowly?"),
            ("compliance", "How do I get USDA certification?"),
        ]

        for category, question in categories:
            faq = FarmerQuestionAnswer.objects.create(
                question=question, answer=f"Answer for {category} question", category=category
            )

            self.assertEqual(faq.category, category)

    def test_faq_popularity_tracking(self):
        """Test FAQ view count and helpful votes."""
        faq = FarmerQuestionAnswer.objects.create(
            question="How do I reduce my carbon footprint?",
            answer="Implement sustainable practices and track with Trazo",
            category="carbon",
            view_count=150,
            helpful_votes=45,
        )

        # Simulate views
        faq.view_count += 10
        faq.save()

        # Simulate helpful votes
        faq.helpful_votes += 5
        faq.save()

        self.assertEqual(faq.view_count, 160)
        self.assertEqual(faq.helpful_votes, 50)

    def test_faq_ordering(self):
        """Test FAQ ordering by popularity."""
        faq1 = FarmerQuestionAnswer.objects.create(
            question="Less popular question", answer="Answer 1", category="setup", helpful_votes=10, view_count=50
        )

        faq2 = FarmerQuestionAnswer.objects.create(
            question="Most popular question", answer="Answer 2", category="setup", helpful_votes=100, view_count=500
        )

        faq3 = FarmerQuestionAnswer.objects.create(
            question="Moderately popular question",
            answer="Answer 3",
            category="setup",
            helpful_votes=50,
            view_count=200,
        )

        faqs = FarmerQuestionAnswer.objects.all()
        self.assertEqual(faqs[0], faq2)  # Most helpful votes first
        self.assertEqual(faqs[1], faq3)  # Second most helpful
        self.assertEqual(faqs[2], faq1)  # Least helpful


class EducationAPITestCase(APITestCase):
    """Test Education API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        # Create users
        self.farmer = User.objects.create_user(email="farmer@test.com", password="testpass123", user_type="producer")

        self.staff = User.objects.create_user(email="staff@test.com", password="testpass123", is_staff=True)

        # Create educational content
        self.category = EducationCategory.objects.create(
            name="Getting Started", category_type="getting_started", description="Basic Trazo usage"
        )

        self.course = EducationCourse.objects.create(
            title="Trazo Basics",
            category=self.category,
            description="Learn Trazo fundamentals",
            difficulty="beginner",
            estimated_duration=30,
        )

        self.lesson = EducationLesson.objects.create(
            course=self.course,
            title="Creating Your First Event",
            content_type="video",
            content="Learn to create farm events",
            duration=10,
        )

    def test_list_courses_authenticated(self):
        """Test listing courses requires authentication."""
        url = reverse("education:course-list")

        # Unauthenticated request should fail
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request should succeed
        self.client.force_authenticate(user=self.farmer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_course_filtering_by_difficulty(self):
        """Test filtering courses by difficulty level."""
        # Create courses with different difficulties
        advanced_course = EducationCourse.objects.create(
            title="Advanced Analytics",
            category=self.category,
            description="Advanced features",
            difficulty="advanced",
            estimated_duration=90,
        )

        self.client.force_authenticate(user=self.farmer)
        url = reverse("education:course-list")

        # Filter by beginner difficulty
        response = self.client.get(url, {"difficulty": "beginner"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Trazo Basics")

        # Filter by advanced difficulty
        response = self.client.get(url, {"difficulty": "advanced"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Advanced Analytics")

    def test_lesson_progress_tracking(self):
        """Test tracking lesson progress via API."""
        self.client.force_authenticate(user=self.farmer)
        url = reverse("education:lesson-progress", kwargs={"pk": self.lesson.pk})

        data = {"time_spent": 12, "quiz_score": 85, "helpful_rating": 4, "feedback": "Very helpful video!"}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify progress was recorded
        progress = UserEducationProgress.objects.get(user=self.farmer, lesson=self.lesson)
        self.assertEqual(progress.time_spent, 12)
        self.assertEqual(progress.quiz_score, 85)

    def test_lesson_completion(self):
        """Test marking lesson as completed via API."""
        self.client.force_authenticate(user=self.farmer)
        url = reverse("education:lesson-complete", kwargs={"pk": self.lesson.pk})

        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify lesson was marked as completed
        progress = UserEducationProgress.objects.get(user=self.farmer, lesson=self.lesson)
        self.assertTrue(progress.is_completed)

    def test_bookmark_lesson(self):
        """Test bookmarking lesson via API."""
        self.client.force_authenticate(user=self.farmer)
        url = reverse("education:lesson-bookmark", kwargs={"pk": self.lesson.pk})

        data = {"notes": "Important for my sensor setup"}

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify bookmark was created
        bookmark = EducationBookmark.objects.get(user=self.farmer, lesson=self.lesson)
        self.assertEqual(bookmark.notes, "Important for my sensor setup")

    def test_staff_content_management(self):
        """Test staff can manage educational content."""
        self.client.force_authenticate(user=self.staff)
        url = reverse("education:course-list")

        data = {
            "title": "New Staff Course",
            "category": self.category.id,
            "description": "Course created by staff",
            "difficulty": "intermediate",
            "estimated_duration": 60,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify course was created
        course = EducationCourse.objects.get(title="New Staff Course")
        self.assertEqual(course.difficulty, "intermediate")

    def test_farmer_cannot_create_content(self):
        """Test farmers cannot create educational content."""
        self.client.force_authenticate(user=self.farmer)
        url = reverse("education:course-list")

        data = {
            "title": "Unauthorized Course",
            "category": self.category.id,
            "description": "Should not be allowed",
            "difficulty": "beginner",
            "estimated_duration": 30,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EducationAnalyticsTestCase(TestCase):
    """Test education analytics and reporting."""

    def setUp(self):
        self.category = EducationCategory.objects.create(
            name="Analytics Test", category_type="carbon_tracking", description="Test category"
        )

        self.course = EducationCourse.objects.create(
            title="Analytics Course",
            category=self.category,
            description="Test course",
            difficulty="beginner",
            estimated_duration=60,
        )

        # Create multiple users and lessons
        self.users = []
        self.lessons = []

        for i in range(10):
            user = User.objects.create_user(email=f"user{i}@test.com", password="testpass123")
            self.users.append(user)

        for i in range(5):
            lesson = EducationLesson.objects.create(
                course=self.course,
                title=f"Lesson {i+1}",
                content_type="text",
                content=f"Content {i+1}",
                duration=12,
                order=i + 1,
            )
            self.lessons.append(lesson)

    def test_course_completion_analytics(self):
        """Test course completion rate analytics."""
        # Create progress for users (some completed, some not)
        for i, user in enumerate(self.users):
            for j, lesson in enumerate(self.lessons):
                progress = UserEducationProgress.objects.create(
                    user=user, lesson=lesson, time_spent=10 + j, quiz_score=75 + (j * 5)
                )

                # Mark as completed for some users
                if i < 6 and j < 3:  # 6 users complete first 3 lessons
                    progress.completed_at = timezone.now()
                    progress.save()

        # Calculate completion analytics
        total_users = len(self.users)
        completed_all_lessons = 0

        for user in self.users:
            user_progress = UserEducationProgress.objects.filter(
                user=user, lesson__course=self.course, completed_at__isnull=False
            )
            if user_progress.count() == len(self.lessons):
                completed_all_lessons += 1

        completion_rate = (completed_all_lessons / total_users) * 100

        # No users completed ALL lessons (only first 3), so rate should be 0
        self.assertEqual(completion_rate, 0.0)

    def test_lesson_engagement_analytics(self):
        """Test lesson engagement metrics."""
        # Create varied engagement data
        for i, lesson in enumerate(self.lessons):
            for j, user in enumerate(self.users):
                if j <= i + 2:  # Decreasing engagement per lesson
                    UserEducationProgress.objects.create(
                        user=user,
                        lesson=lesson,
                        time_spent=15 + (j % 5),
                        helpful_rating=(j % 5) + 1,
                        completed_at=timezone.now() if j % 2 == 0 else None,
                    )

        # Calculate engagement metrics
        for lesson in self.lessons:
            progress_records = UserEducationProgress.objects.filter(lesson=lesson)

            total_learners = progress_records.count()
            completed_count = progress_records.filter(completed_at__isnull=False).count()
            avg_time = progress_records.aggregate(avg_time=Avg("time_spent"))["avg_time"]
            avg_rating = progress_records.aggregate(avg_rating=Avg("helpful_rating"))["avg_rating"]

            self.assertGreater(total_learners, 0)
            self.assertIsNotNone(avg_time)
            self.assertIsNotNone(avg_rating)

    def test_content_popularity_analytics(self):
        """Test content popularity rankings."""
        # Create varied progress data
        lesson_engagement = {}

        for i, lesson in enumerate(self.lessons):
            engagement_count = 8 - i  # Decreasing engagement
            lesson_engagement[lesson.id] = engagement_count

            for j in range(engagement_count):
                user = self.users[j]
                UserEducationProgress.objects.create(
                    user=user, lesson=lesson, time_spent=20, helpful_rating=4 + (j % 2), completed_at=timezone.now()
                )

        # Verify popularity ranking
        popular_lessons = EducationLesson.objects.annotate(engagement_count=Count("usereducationprogress")).order_by(
            "-engagement_count"
        )

        # First lesson should be most popular
        self.assertEqual(popular_lessons[0], self.lessons[0])
        self.assertEqual(popular_lessons.last(), self.lessons[-1])


class EducationPerformanceTestCase(TestCase):
    """Test education system performance optimizations."""

    def setUp(self):
        self.category = EducationCategory.objects.create(
            name="Performance Test", category_type="iot_automation", description="Performance testing"
        )

    def test_bulk_content_creation(self):
        """Test bulk creation of educational content."""
        # Bulk create courses
        courses_data = []
        for i in range(50):
            courses_data.append(
                EducationCourse(
                    title=f"Bulk Course {i}",
                    category=self.category,
                    description=f"Bulk description {i}",
                    difficulty="beginner",
                    estimated_duration=30,
                )
            )

        created_courses = EducationCourse.objects.bulk_create(courses_data)
        self.assertEqual(len(created_courses), 50)

        # Bulk create lessons for first course
        lessons_data = []
        course = created_courses[0]
        for i in range(20):
            lessons_data.append(
                EducationLesson(
                    course=course,
                    title=f"Bulk Lesson {i}",
                    content_type="text",
                    content=f"Bulk content {i}",
                    duration=10,
                    order=i + 1,
                )
            )

        created_lessons = EducationLesson.objects.bulk_create(lessons_data)
        self.assertEqual(len(created_lessons), 20)

    def test_progress_queryset_optimization(self):
        """Test optimized queries for progress tracking."""
        # Create test data
        course = EducationCourse.objects.create(
            title="Query Test Course",
            category=self.category,
            description="For query optimization testing",
            difficulty="intermediate",
            estimated_duration=60,
        )

        users = []
        lessons = []

        for i in range(20):
            user = User.objects.create_user(email=f"queryuser{i}@test.com", password="testpass123")
            users.append(user)

        for i in range(10):
            lesson = EducationLesson.objects.create(
                course=course, title=f"Query Lesson {i}", content_type="text", content=f"Query content {i}", duration=15
            )
            lessons.append(lesson)

        # Create progress records
        for user in users:
            for lesson in lessons[:5]:  # Each user progresses through first 5 lessons
                UserEducationProgress.objects.create(
                    user=user, lesson=lesson, time_spent=15, completed_at=timezone.now()
                )

        # Test optimized query with select_related and prefetch_related
        progress_records = (
            UserEducationProgress.objects.select_related("user", "lesson", "lesson__course")
            .prefetch_related("lesson__course__category")
            .all()
        )

        self.assertEqual(len(list(progress_records)), 100)  # 20 users * 5 lessons

    def test_analytics_aggregation_performance(self):
        """Test performance of analytics aggregation queries."""
        # Create substantial test data
        course = EducationCourse.objects.create(
            title="Analytics Performance Test",
            category=self.category,
            description="Large dataset for analytics",
            difficulty="advanced",
            estimated_duration=120,
        )

        for i in range(100):
            user = User.objects.create_user(email=f"perfuser{i}@test.com", password="testpass123")

            lesson = EducationLesson.objects.create(
                course=course,
                title=f"Performance Lesson {i}",
                content_type="text",
                content=f"Performance content {i}",
                duration=20,
            )

            UserEducationProgress.objects.create(
                user=user,
                lesson=lesson,
                time_spent=18 + (i % 10),
                quiz_score=75 + (i % 25),
                helpful_rating=(i % 5) + 1,
                completed_at=timezone.now() if i % 3 == 0 else None,
            )

        # Complex aggregation query
        analytics = UserEducationProgress.objects.filter(lesson__course=course).aggregate(
            total_learners=Count("user", distinct=True),
            total_completions=Count("id", filter=Q(completed_at__isnull=False)),
            avg_time_spent=Avg("time_spent"),
            avg_quiz_score=Avg("quiz_score"),
            avg_helpful_rating=Avg("helpful_rating"),
            completion_rate=Count("id", filter=Q(completed_at__isnull=False)) * 100.0 / Count("id"),
        )

        self.assertEqual(analytics["total_learners"], 100)
        self.assertIsNotNone(analytics["avg_time_spent"])
        self.assertIsNotNone(analytics["avg_quiz_score"])
        self.assertGreater(analytics["completion_rate"], 0)
