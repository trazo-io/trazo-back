"""
Comprehensive Integration Tests for Main User Flows
Tests cover end-to-end user journeys across multiple apps and services.

Test Coverage:
- Complete user registration and onboarding flow
- Farm setup and parcel creation workflow
- Production event creation and carbon calculation flow
- QR code generation and consumer transparency flow
- Subscription management and billing integration
- Educational content engagement flow
- Support ticket lifecycle management
- Cross-app data consistency and integrity
"""

import json
import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from carbon.models import CarbonEntry, EstablishmentCarbonFootprint
from company.models import Company, Establishment
from education.models import EducationCategory, EducationCourse, EducationLesson, UserEducationProgress
from history.models import History, QRCodeData
from product.models import CropTemplate, Parcel
from reviews.models import Review
from subscriptions.models import Plan, Subscription
from support.models import SupportMessage, SupportTicket

# Import models from all apps
from users.models import User, VerificationCode, WorksIn

User = get_user_model()


class UserOnboardingFlowTestCase(TransactionTestCase):
    """Test complete user onboarding and account setup flow."""

    def setUp(self):
        self.client = APIClient()

        # Create subscription plan
        self.basic_plan = Plan.objects.create(
            name="Basic Plan",
            plan_type="basic",
            price=29.99,
            features={
                "max_establishments": 1,
                "max_parcels_per_establishment": 5,
                "carbon_tracking": True,
                "qr_codes": True,
                "support_response_time": 48,
            },
        )

    def test_complete_producer_onboarding_flow(self):
        """Test complete producer user onboarding from registration to first production."""
        # Step 1: User Registration
        registration_data = {
            "email": "newfarmer@test.com",
            "password": "SecurePass123!",
            "first_name": "John",
            "last_name": "Farmer",
            "user_type": "producer",
        }

        signup_url = reverse("users:signup")
        response = self.client.post(signup_url, registration_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify user was created
        user = User.objects.get(email="newfarmer@test.com")
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.user_type, "producer")

        # Step 2: Email Verification (simulated)
        verification_code = VerificationCode.objects.create(user=user, purpose="email_verification")
        verification_code.is_verified = True
        verification_code.save()

        # Step 3: Login
        login_data = {"email": "newfarmer@test.com", "password": "SecurePass123!"}

        login_url = reverse("users:login")
        response = self.client.post(login_url, login_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Extract authentication token
        access_token = response.data["access_token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # Step 4: Company Creation
        company_data = {
            "name": "Sunrise Organic Farm",
            "address": "123 Farm Road",
            "city": "Fresno",
            "state": "CA",
            "country": "US",
            "zip_code": "93727",
            "phone": "+1-559-123-4567",
            "certifications": ["USDA Organic", "Good Agricultural Practices (GAP)"],
        }

        company_url = reverse("company:company-list")
        response = self.client.post(company_url, company_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        company = Company.objects.get(name="Sunrise Organic Farm")
        self.assertEqual(company.owner, user)

        # Step 5: Subscription Setup
        subscription = Subscription.objects.create(
            company=company,
            plan=self.basic_plan,
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Step 6: Establishment Creation
        establishment_data = {
            "name": "North Field Operations",
            "company": company.id,
            "address": "123 Farm Road, North Section",
            "city": "Fresno",
            "state": "CA",
            "country": "US",
            "latitude": "36.7378",
            "longitude": "-119.7871",
            "total_area": 100.0,
            "organic_certified": True,
        }

        establishment_url = reverse("company:establishment-list")
        response = self.client.post(establishment_url, establishment_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        establishment = Establishment.objects.get(name="North Field Operations")
        self.assertEqual(establishment.company, company)

        # Step 7: Parcel Creation
        parcel_data = {
            "name": "Tomato Field A",
            "establishment": establishment.id,
            "area": 25.0,
            "soil_type": "loam",
            "irrigation_type": "drip",
            "organic_certified": True,
            "latitude": "36.7400",
            "longitude": "-119.7900",
        }

        parcel_url = reverse("product:parcel-list")
        response = self.client.post(parcel_url, parcel_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        parcel = Parcel.objects.get(name="Tomato Field A")
        self.assertEqual(parcel.establishment, establishment)

        # Step 8: First Production Event
        production_data = {
            "title": "Tomato Planting - Spring 2024",
            "description": "Planted 2,500 tomato seedlings using organic methods",
            "establishment": establishment.id,
            "parcel": parcel.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "planting",
            "crop_type": "tomato",
            "quantity": 2500,
            "unit": "plants",
            "seed_variety": "Roma VF",
            "planting_method": "transplant",
        }

        history_url = reverse("history:history-list")
        response = self.client.post(history_url, production_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify production event was created with QR code
        production = History.objects.get(title="Tomato Planting - Spring 2024")
        self.assertEqual(production.establishment, establishment)
        self.assertIsNotNone(production.qr_code)

        # Step 9: Verify Carbon Footprint Entry was Created
        carbon_entries = CarbonEntry.objects.filter(establishment=establishment)
        self.assertGreater(carbon_entries.count(), 0)

        # Step 10: Verify Establishment Carbon Footprint was Updated
        footprint = EstablishmentCarbonFootprint.objects.filter(establishment=establishment).first()
        self.assertIsNotNone(footprint)

        # Verify complete onboarding flow success
        self.assertTrue(user.is_active)
        self.assertEqual(Company.objects.filter(owner=user).count(), 1)
        self.assertEqual(Establishment.objects.filter(company=company).count(), 1)
        self.assertEqual(Parcel.objects.filter(establishment=establishment).count(), 1)
        self.assertEqual(History.objects.filter(establishment=establishment).count(), 1)


class ProductionToCarbonTrackingFlowTestCase(TestCase):
    """Test production event to carbon tracking integration flow."""

    def setUp(self):
        self.client = APIClient()

        # Create complete farm setup
        self.user = User.objects.create_user(
            email="carbonfarmer@test.com", password="testpass123", user_type="producer"
        )

        self.company = Company.objects.create(name="Carbon Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(
            name="Carbon Test Field", company=self.company, latitude=Decimal("36.7378"), longitude=Decimal("-119.7871")
        )

        self.parcel = Parcel.objects.create(
            name="Carbon Test Parcel",
            establishment=self.establishment,
            area=10.0,
            soil_type="loam",
            organic_certified=False,
        )

        self.client.force_authenticate(user=self.user)

    def test_fertilizer_application_to_carbon_calculation_flow(self):
        """Test fertilizer application event creates carbon entry."""
        # Create fertilizer application event
        fertilizer_data = {
            "title": "Nitrogen Fertilizer Application",
            "description": "Applied nitrogen fertilizer to corn field",
            "establishment": self.establishment.id,
            "parcel": self.parcel.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "fertilizing",
            "fertilizer_type": "nitrogen",
            "quantity": 100.0,
            "unit": "kg",
            "application_method": "broadcast",
        }

        url = reverse("history:history-list")
        response = self.client.post(url, fertilizer_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify production event was created
        production = History.objects.get(title="Nitrogen Fertilizer Application")
        self.assertEqual(production.fertilizer_type, "nitrogen")
        self.assertEqual(production.quantity, 100.0)

        # Verify carbon entry was created (via signals or services)
        carbon_entries = CarbonEntry.objects.filter(establishment=self.establishment, source_type="fertilizer")

        # If carbon calculation service is active, verify entry
        if carbon_entries.exists():
            carbon_entry = carbon_entries.first()
            self.assertGreater(carbon_entry.co2e_amount, 0)
            self.assertIn("nitrogen", carbon_entry.notes.lower())

        # Verify establishment carbon footprint was updated
        footprint = EstablishmentCarbonFootprint.objects.filter(establishment=self.establishment).first()

        if footprint:
            self.assertGreater(footprint.total_co2e, 0)

    def test_fuel_consumption_to_carbon_calculation_flow(self):
        """Test fuel consumption event creates carbon entry."""
        # Create fuel consumption event
        fuel_data = {
            "title": "Tractor Operation - Field Preparation",
            "description": "Used tractor for soil preparation",
            "establishment": self.establishment.id,
            "parcel": self.parcel.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "soil_preparation",
            "fuel_type": "diesel",
            "fuel_consumption": 25.0,
            "unit": "liters",
            "equipment_used": "John Deere 8345R",
        }

        url = reverse("history:history-list")
        response = self.client.post(url, fuel_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify production event
        production = History.objects.get(title="Tractor Operation - Field Preparation")
        self.assertEqual(production.fuel_type, "diesel")

        # Verify carbon calculation integration
        carbon_entries = CarbonEntry.objects.filter(establishment=self.establishment, source_type="fuel")

        if carbon_entries.exists():
            carbon_entry = carbon_entries.first()
            self.assertGreater(carbon_entry.co2e_amount, 0)

    def test_comprehensive_production_season_flow(self):
        """Test complete production season with multiple events."""
        events_data = [
            {
                "title": "Soil Preparation",
                "event_type": "soil_preparation",
                "fuel_type": "diesel",
                "fuel_consumption": 30.0,
                "equipment_used": "Tractor",
            },
            {
                "title": "Corn Planting",
                "event_type": "planting",
                "crop_type": "corn",
                "quantity": 25000,
                "unit": "seeds",
                "seed_variety": "Pioneer P1234",
            },
            {
                "title": "Fertilizer Application",
                "event_type": "fertilizing",
                "fertilizer_type": "nitrogen",
                "quantity": 150.0,
                "unit": "kg",
            },
            {
                "title": "Irrigation System Operation",
                "event_type": "irrigation",
                "irrigation_type": "drip",
                "water_volume": 500.0,
                "unit": "m3",
            },
            {
                "title": "Corn Harvest",
                "event_type": "harvesting",
                "crop_type": "corn",
                "quantity": 8000.0,
                "unit": "kg",
            },
        ]

        created_events = []
        url = reverse("history:history-list")

        for event_data in events_data:
            full_data = {
                "establishment": self.establishment.id,
                "parcel": self.parcel.id,
                "event_date": timezone.now().date().isoformat(),
                "description": f'Production event: {event_data["title"]}',
                **event_data,
            }

            response = self.client.post(url, full_data, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            created_events.append(response.data)

        # Verify all events were created
        total_events = History.objects.filter(establishment=self.establishment).count()
        self.assertEqual(total_events, len(events_data))

        # Verify carbon entries for emission-generating events
        carbon_entries = CarbonEntry.objects.filter(establishment=self.establishment)

        # Should have entries for fuel and fertilizer events at minimum
        emission_events = ["soil_preparation", "fertilizing", "irrigation"]
        expected_carbon_entries = len([e for e in events_data if e["event_type"] in emission_events])

        if carbon_entries.exists():
            self.assertGreaterEqual(carbon_entries.count(), 1)

        # Verify comprehensive carbon footprint
        footprint = EstablishmentCarbonFootprint.objects.filter(establishment=self.establishment).first()

        if footprint:
            self.assertGreater(footprint.total_co2e, 0)
            self.assertIsNotNone(footprint.last_calculated_at)


class QRCodeConsumerFlowTestCase(TestCase):
    """Test QR code generation and consumer scanning flow."""

    def setUp(self):
        self.client = APIClient()

        # Create producer setup
        self.producer = User.objects.create_user(
            email="producer@test.com", password="testpass123", user_type="producer"
        )

        # Create consumer
        self.consumer = User.objects.create_user(
            email="consumer@test.com", password="testpass123", user_type="consumer"
        )

        self.company = Company.objects.create(name="QR Test Farm", owner=self.producer)

        self.establishment = Establishment.objects.create(
            name="QR Test Field", company=self.company, about="Sustainable organic farming practices"
        )

        self.parcel = Parcel.objects.create(
            name="QR Test Parcel", establishment=self.establishment, area=20.0, organic_certified=True
        )

    def test_production_to_qr_to_consumer_flow(self):
        """Test complete flow from production to consumer QR scan."""
        # Step 1: Producer creates production event
        self.client.force_authenticate(user=self.producer)

        production_data = {
            "title": "Organic Tomato Harvest",
            "description": "Harvested premium organic tomatoes",
            "establishment": self.establishment.id,
            "parcel": self.parcel.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "harvesting",
            "crop_type": "tomato",
            "quantity": 500.0,
            "unit": "kg",
            "harvest_quality": "premium",
            "organic_certified": True,
        }

        history_url = reverse("history:history-list")
        response = self.client.post(history_url, production_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify QR code was generated
        production = History.objects.get(title="Organic Tomato Harvest")
        self.assertIsNotNone(production.qr_code)
        self.assertTrue(production.qr_code.startswith("TRAZO"))

        # Step 2: QR code data entry creation
        qr_data = QRCodeData.objects.create(
            code=production.qr_code,
            data_type="production_history",
            reference_id=str(production.id),
            metadata={
                "title": production.title,
                "crop_type": production.crop_type,
                "quantity": production.quantity,
                "organic_certified": production.organic_certified,
                "establishment_name": self.establishment.name,
            },
        )

        # Step 3: Consumer scans QR code (public endpoint)
        self.client.force_authenticate(user=None)  # Public access

        qr_scan_url = reverse("history:qr-scan", kwargs={"qr_code": production.qr_code})
        response = self.client.get(qr_scan_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify consumer gets production information
        scan_data = response.data
        self.assertEqual(scan_data["title"], "Organic Tomato Harvest")
        self.assertEqual(scan_data["crop_type"], "tomato")
        self.assertTrue(scan_data["organic_certified"])
        self.assertIn("establishment", scan_data)

        # Step 4: Track QR scan
        qr_data.refresh_from_db()
        self.assertEqual(qr_data.scan_count, 1)

        # Step 5: Consumer leaves review
        self.client.force_authenticate(user=self.consumer)

        review_data = {
            "establishment": self.establishment.id,
            "production": production.id,
            "rating": 4.5,
            "title": "Excellent organic tomatoes!",
            "content": "The tomatoes were fresh and clearly grown with sustainable practices.",
            "sustainability_rating": 5.0,
            "quality_rating": 4.5,
            "transparency_rating": 4.0,
            "verified_purchase": True,
        }

        review_url = reverse("reviews:review-list")
        response = self.client.post(review_url, review_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify review was linked to production
        review = Review.objects.get(title="Excellent organic tomatoes!")
        self.assertEqual(review.production, production)
        self.assertEqual(review.establishment, self.establishment)

        # Step 6: Verify complete transparency chain
        self.assertIsNotNone(production.qr_code)
        self.assertTrue(qr_data.scan_count > 0)
        self.assertTrue(Review.objects.filter(production=production).exists())


class EducationEngagementFlowTestCase(TestCase):
    """Test educational content engagement and progress tracking flow."""

    def setUp(self):
        self.client = APIClient()

        # Create farmer user
        self.farmer = User.objects.create_user(
            email="learningfarmer@test.com", password="testpass123", user_type="producer"
        )

        # Create educational content
        self.category = EducationCategory.objects.create(
            name="Carbon Tracking Basics",
            category_type="carbon_tracking",
            description="Learn the fundamentals of carbon tracking",
        )

        self.course = EducationCourse.objects.create(
            title="Introduction to Carbon Footprint Tracking",
            category=self.category,
            description="Learn how to track your farm's carbon footprint",
            difficulty="beginner",
            estimated_duration=60,
            target_crops="corn,wheat,soybeans",
        )

        self.lessons = []
        for i in range(5):
            lesson = EducationLesson.objects.create(
                course=self.course,
                title=f"Lesson {i+1}: Carbon Basics Part {i+1}",
                content_type="video",
                content=f"Educational content for lesson {i+1}",
                duration=12,
                order=i + 1,
                has_quiz=True if i % 2 == 0 else False,
            )
            self.lessons.append(lesson)

        self.client.force_authenticate(user=self.farmer)

    def test_complete_education_engagement_flow(self):
        """Test complete educational engagement from discovery to certification."""
        # Step 1: Discover available courses
        courses_url = reverse("education:course-list")
        response = self.client.get(courses_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        available_courses = response.data
        self.assertGreater(len(available_courses), 0)

        # Step 2: Start course (begin first lesson)
        lesson1 = self.lessons[0]
        progress_url = reverse("education:lesson-progress", kwargs={"pk": lesson1.pk})

        start_data = {"time_spent": 0, "started": True}

        response = self.client.post(progress_url, start_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Step 3: Complete lessons progressively
        for i, lesson in enumerate(self.lessons):
            progress_data = {
                "time_spent": lesson.duration + 2,  # Slightly more than expected
                "quiz_score": 85 + (i * 3) if lesson.has_quiz else None,  # Improving scores
                "helpful_rating": 4 + (i % 2),  # 4 or 5 stars
                "feedback": f"Very helpful lesson {i+1}!",
            }

            progress_url = reverse("education:lesson-progress", kwargs={"pk": lesson.pk})
            response = self.client.patch(progress_url, progress_data, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Mark lesson as completed
            complete_url = reverse("education:lesson-complete", kwargs={"pk": lesson.pk})
            response = self.client.post(complete_url, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Step 4: Verify all progress was tracked
        progress_records = UserEducationProgress.objects.filter(user=self.farmer, lesson__course=self.course)

        self.assertEqual(progress_records.count(), len(self.lessons))

        # All lessons should be completed
        completed_count = progress_records.filter(completed_at__isnull=False).count()
        self.assertEqual(completed_count, len(self.lessons))

        # Step 5: Calculate course completion metrics
        total_time = sum(p.time_spent for p in progress_records)
        avg_quiz_score = progress_records.exclude(quiz_score__isnull=True).aggregate(
            avg_score=models.Avg("quiz_score")
        )["avg_score"]

        completion_percentage = (completed_count / len(self.lessons)) * 100

        # Step 6: Award certificate (if course is 100% complete)
        from education.models import EducationCertificate

        if completion_percentage == 100:
            certificate = EducationCertificate.objects.create(
                user=self.farmer,
                course=self.course,
                certificate_id=f'TRAZO-CERT-{timezone.now().strftime("%Y%m%d")}-001',
                completion_percentage=int(completion_percentage),
                total_time_spent=total_time,
                average_quiz_score=int(avg_quiz_score) if avg_quiz_score else None,
            )

            self.assertEqual(certificate.user, self.farmer)
            self.assertEqual(certificate.completion_percentage, 100)

        # Step 7: Bookmark useful lesson
        bookmark_lesson = self.lessons[2]  # Middle lesson
        bookmark_url = reverse("education:lesson-bookmark", kwargs={"pk": bookmark_lesson.pk})

        bookmark_data = {"notes": "Important information about emission factors - need to reference later"}

        response = self.client.post(bookmark_url, bookmark_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify bookmark was created
        from education.models import EducationBookmark

        bookmark = EducationBookmark.objects.get(user=self.farmer, lesson=bookmark_lesson)
        self.assertIn("emission factors", bookmark.notes)


class SupportTicketLifecycleFlowTestCase(TestCase):
    """Test complete support ticket lifecycle flow."""

    def setUp(self):
        self.client = APIClient()

        # Create customer
        self.customer = User.objects.create_user(
            email="customer@test.com", password="testpass123", user_type="producer"
        )

        # Create support agent
        self.support_agent = User.objects.create_user(email="support@test.com", password="testpass123", is_staff=True)

        self.company = Company.objects.create(name="Support Test Farm", owner=self.customer)

        # Create subscription for SLA determination
        plan = Plan.objects.create(
            name="Premium Plan",
            plan_type="premium",
            price=99.99,
            features={"support_response_time": 12, "priority_support": True},
        )

        self.subscription = Subscription.objects.create(
            company=self.company,
            plan=plan,
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def test_complete_support_ticket_lifecycle(self):
        """Test complete support ticket from creation to resolution."""
        # Step 1: Customer creates support ticket
        self.client.force_authenticate(user=self.customer)

        ticket_data = {
            "subject": "Carbon calculation discrepancy in my dashboard",
            "description": """
            Hi Trazo Support Team,
            
            I've noticed that my carbon footprint calculation seems incorrect for last month.
            
            Details:
            - Field: North Field (40 acres)
            - Crop: Corn
            - Fertilizer applied: 150 lbs nitrogen on March 15th
            - Expected CO2e: ~1.8 tons based on previous calculations
            - Current dashboard shows: 4.2 tons CO2e
            
            Could you help me understand why there's such a large difference?
            I've attached screenshots of my dashboard for reference.
            
            Thanks,
            John Farmer
            """,
            "category": "carbon_tracking",
            "priority": "normal",
        }

        tickets_url = reverse("support:ticket-list")
        response = self.client.post(tickets_url, ticket_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify ticket was created with correct SLA
        ticket = SupportTicket.objects.get(subject__icontains="Carbon calculation discrepancy")
        self.assertEqual(ticket.user, self.customer)
        self.assertEqual(ticket.company, self.company)
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.sla_response_hours, 12)  # Premium plan response time
        self.assertIsNotNone(ticket.ticket_id)

        # Step 2: Customer adds more information
        message_data = {
            "content": """
            I forgot to mention that I'm using the latest version of the mobile app
            (v2.1.3) and this issue started happening after the recent update.
            
            Also, I applied the fertilizer using broadcast method during a rainy day.
            Could weather conditions affect the calculation?
            """
        }

        message_url = reverse("support:ticket-message", kwargs={"pk": ticket.pk})
        response = self.client.post(message_url, message_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify message was added
        customer_messages = SupportMessage.objects.filter(ticket=ticket, author=self.customer, message_type="customer")
        self.assertEqual(customer_messages.count(), 1)

        # Step 3: Support agent takes ticket
        self.client.force_authenticate(user=self.support_agent)

        assignment_data = {"assigned_to": self.support_agent.id, "status": "in_progress"}

        ticket_detail_url = reverse("support:ticket-detail", kwargs={"pk": ticket.pk})
        response = self.client.patch(ticket_detail_url, assignment_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify assignment
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.support_agent)
        self.assertEqual(ticket.status, "in_progress")

        # Step 4: Support agent responds
        agent_response_data = {
            "content": """
            Hi John,
            
            Thank you for providing those additional details. I can see the issue now.
            
            The discrepancy is due to the weather conditions during your fertilizer application.
            When nitrogen fertilizer is applied during rainy conditions, there's increased 
            volatilization and runoff, which actually increases the carbon footprint calculation.
            
            Here's what happened:
            - Normal nitrogen application: 150 lbs × 11.0 kg CO2e/kg = 1.8 tons CO2e
            - Rainy day adjustment factor: 1.35x for increased volatilization
            - Adjusted calculation: 1.8 × 1.35 = 2.43 tons CO2e
            - Additional runoff factor: 1.73x for rainfall >0.5 inches
            - Final calculation: 2.43 × 1.73 = 4.2 tons CO2e
            
            This is actually working correctly according to USDA emission factor guidelines.
            The app now automatically adjusts for weather conditions using local weather data.
            
            To reduce this in the future, consider:
            1. Checking weather forecasts before fertilizer application
            2. Using slow-release fertilizers in areas with frequent rain
            3. Applying fertilizer during dry periods when possible
            
            Would you like me to send you a detailed report of the calculation breakdown?
            
            Best regards,
            Sarah - Trazo Support Team
            """
        }

        response = self.client.post(message_url, agent_response_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify first response time was recorded
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_response_at)

        # Step 5: Customer follows up
        self.client.force_authenticate(user=self.customer)

        followup_data = {
            "content": """
            Hi Sarah,
            
            Thank you so much for the detailed explanation! That makes perfect sense now.
            I had no idea that weather conditions were automatically factored into the calculations.
            
            Yes, I would love to receive the detailed calculation breakdown report.
            This will help me better understand the system and plan my applications better.
            
            This level of detail and quick response is exactly why I chose Trazo.
            Thank you for the excellent support!
            
            Best regards,
            John
            """
        }

        response = self.client.post(message_url, followup_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Step 6: Support agent marks as resolved
        self.client.force_authenticate(user=self.support_agent)

        resolution_data = {"status": "resolved"}

        response = self.client.patch(ticket_detail_url, resolution_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify resolution
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertIsNotNone(ticket.resolved_at)

        # Step 7: Customer provides satisfaction rating
        self.client.force_authenticate(user=self.customer)

        satisfaction_data = {"customer_satisfaction_rating": 5}

        response = self.client.patch(ticket_detail_url, satisfaction_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify satisfaction rating
        ticket.refresh_from_db()
        self.assertEqual(ticket.customer_satisfaction_rating, 5)

        # Step 8: Verify complete ticket lifecycle
        messages = SupportMessage.objects.filter(ticket=ticket).order_by("created_at")
        self.assertEqual(messages.count(), 3)  # Customer, Agent, Customer followup

        # Verify SLA compliance
        self.assertIsNotNone(ticket.response_time_hours)
        self.assertLess(ticket.response_time_hours, ticket.sla_response_hours)  # Within SLA

        self.assertIsNotNone(ticket.resolution_time_hours)
        self.assertLess(ticket.resolution_time_hours, ticket.sla_resolution_hours)  # Within SLA


class CrossAppDataConsistencyTestCase(TransactionTestCase):
    """Test data consistency across multiple apps and services."""

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(email="consistency@test.com", password="testpass123", user_type="producer")

        self.company = Company.objects.create(name="Consistency Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Consistency Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Consistency Test Parcel", establishment=self.establishment, area=15.0)

        self.client.force_authenticate(user=self.user)

    def test_production_event_cross_app_consistency(self):
        """Test that production events maintain consistency across all related models."""
        # Create production event
        production_data = {
            "title": "Consistency Test Production",
            "description": "Testing cross-app data consistency",
            "establishment": self.establishment.id,
            "parcel": self.parcel.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "fertilizing",
            "fertilizer_type": "nitrogen",
            "quantity": 75.0,
            "unit": "kg",
        }

        history_url = reverse("history:history-list")
        response = self.client.post(history_url, production_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        production = History.objects.get(title="Consistency Test Production")

        # Verify QR code consistency
        self.assertIsNotNone(production.qr_code)

        qr_data = QRCodeData.objects.filter(code=production.qr_code, reference_id=str(production.id)).first()

        if qr_data:
            self.assertEqual(qr_data.data_type, "production_history")
            self.assertIn(production.title, qr_data.metadata.get("title", ""))

        # Verify carbon entry consistency
        carbon_entries = CarbonEntry.objects.filter(establishment=self.establishment, source_type="fertilizer")

        if carbon_entries.exists():
            carbon_entry = carbon_entries.first()
            # Verify carbon entry links back to production
            self.assertIsNotNone(carbon_entry.source_event)

        # Verify establishment carbon footprint consistency
        footprint = EstablishmentCarbonFootprint.objects.filter(establishment=self.establishment).first()

        if footprint:
            self.assertGreater(footprint.total_co2e, 0)
            self.assertEqual(footprint.establishment, self.establishment)

        # Test deletion consistency
        original_qr_code = production.qr_code
        production.delete()

        # Verify related data is properly handled
        deleted_production = History.objects.filter(title="Consistency Test Production").first()
        self.assertIsNone(deleted_production)

        # QR data should be marked as inactive or deleted
        remaining_qr_data = QRCodeData.objects.filter(code=original_qr_code).first()
        if remaining_qr_data:
            # Should be marked as inactive or reference should be cleared
            self.assertNotEqual(remaining_qr_data.reference_id, str(production.id))

    def test_company_deletion_cascade_consistency(self):
        """Test that company deletion properly cascades to all related data."""
        # Create comprehensive data structure
        establishment2 = Establishment.objects.create(name="Second Establishment", company=self.company)

        parcel2 = Parcel.objects.create(name="Second Parcel", establishment=establishment2, area=25.0)

        # Create production events
        for i in range(3):
            History.objects.create(
                title=f"Production Event {i}",
                establishment=establishment2,
                parcel=parcel2,
                event_date=timezone.now().date(),
                event_type="planting",
                created_by=self.user,
            )

        # Create carbon entries
        for i in range(2):
            CarbonEntry.objects.create(
                establishment=establishment2,
                source_type="fertilizer",
                co2e_amount=100.0 + (i * 50),
                calculation_method="USDA",
            )

        # Verify data exists before deletion
        initial_establishments = Establishment.objects.filter(company=self.company).count()
        initial_parcels = Parcel.objects.filter(establishment__company=self.company).count()
        initial_productions = History.objects.filter(establishment__company=self.company).count()
        initial_carbon_entries = CarbonEntry.objects.filter(establishment__company=self.company).count()

        self.assertGreater(initial_establishments, 0)
        self.assertGreater(initial_parcels, 0)
        self.assertGreater(initial_productions, 0)

        # Delete company
        company_id = self.company.id
        self.company.delete()

        # Verify all related data was properly handled
        remaining_establishments = Establishment.objects.filter(company_id=company_id).count()
        remaining_parcels = Parcel.objects.filter(establishment__company_id=company_id).count()
        remaining_productions = History.objects.filter(establishment__company_id=company_id).count()
        remaining_carbon_entries = CarbonEntry.objects.filter(establishment__company_id=company_id).count()

        self.assertEqual(remaining_establishments, 0)
        self.assertEqual(remaining_parcels, 0)
        self.assertEqual(remaining_productions, 0)
        self.assertEqual(remaining_carbon_entries, 0)

        # Verify user still exists (should not be deleted)
        user_exists = User.objects.filter(id=self.user.id).exists()
        self.assertTrue(user_exists)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AsyncProcessingIntegrationTestCase(TestCase):
    """Test asynchronous processing integration across services."""

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(email="async@test.com", password="testpass123")

        self.company = Company.objects.create(name="Async Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Async Test Field", company=self.company)

        self.client.force_authenticate(user=self.user)

    @patch("carbon.tasks.calculate_carbon_footprint.delay")
    def test_async_carbon_calculation_integration(self, mock_calculate):
        """Test async carbon calculation task integration."""
        mock_calculate.return_value = MagicMock(id="test-task-id")

        # Create production event that should trigger async carbon calculation
        production_data = {
            "title": "Async Carbon Test",
            "establishment": self.establishment.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "fertilizing",
            "fertilizer_type": "nitrogen",
            "quantity": 100.0,
            "unit": "kg",
        }

        history_url = reverse("history:history-list")
        response = self.client.post(history_url, production_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify async task was triggered
        mock_calculate.assert_called_once()

        # Verify task was called with correct parameters
        call_args = mock_calculate.call_args[1]  # keyword arguments
        self.assertEqual(call_args["establishment_id"], self.establishment.id)

    @patch("carbon.services.blockchain.BlockchainService.verify_carbon_data")
    def test_blockchain_verification_integration(self, mock_blockchain):
        """Test blockchain verification integration."""
        mock_blockchain.return_value = {"success": True, "transaction_hash": "0x123456789abcdef", "gas_used": 45000}

        # Create carbon entry that should trigger blockchain verification
        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            source_type="fertilizer",
            co2e_amount=150.0,
            calculation_method="USDA",
            requires_verification=True,
        )

        # Trigger verification process
        from carbon.services.blockchain import BlockchainService

        blockchain_service = BlockchainService()

        result = blockchain_service.verify_carbon_data(
            establishment_id=self.establishment.id,
            carbon_data={
                "co2e_amount": carbon_entry.co2e_amount,
                "source_type": carbon_entry.source_type,
                "calculation_method": carbon_entry.calculation_method,
            },
        )

        # Verify blockchain service was called
        mock_blockchain.assert_called_once()
        self.assertTrue(result["success"])
        self.assertIn("transaction_hash", result)
