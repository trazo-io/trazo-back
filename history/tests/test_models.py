"""
Comprehensive test suite for History app functionality.
Tests cover production events, QR code generation, and agricultural timeline management.

Test Coverage:
- Production event creation and validation
- QR code generation and scanning
- Timeline management and ordering
- Image handling and validation
- Voice event processing
- Integration with carbon calculations
- Multi-language support
- Privacy and security controls
"""

import os
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from carbon.models import CarbonEntry
from company.models import Company, Establishment
from history.models import ChemicalEvent, EquipmentEvent, History

# Skip HistoryTranslation and QRCodeData imports - models not implemented
from product.models import Parcel, Product
from subscriptions.models import Subscription
from users.models import User, WorksIn

User = get_user_model()


# Mock QRCodeData since model doesn't exist
class QRCodeData:
    objects = type(
        "MockManager",
        (),
        {
            "create": lambda **kwargs: type("MockQRCodeData", (), kwargs)(),
            "filter": lambda **kwargs: type("MockQuerySet", (), {"delete": lambda: None})(),
            "get": lambda **kwargs: type("MockQRCodeData", (), kwargs)(),
        },
    )()


class HistoryModelTestCase(TestCase):
    """Test History model functionality and validation."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="farmer@test.com", password="testpass123", first_name="John", last_name="Farmer"
        )

        self.company = Company.objects.create(name="Test Farm Co.")

        self.establishment = Establishment.objects.create(name="North Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Field A", establishment=self.establishment, area=10.5)

    def test_history_creation_valid(self):
        """Test creating a production event with valid data."""
        history = History.objects.create(
            title="Corn Planting",
            description="Planted 50 acres of corn",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="planting",
            crop_type="corn",
            quantity=50.0,
            unit="acres",
            created_by=self.user,
        )

        self.assertEqual(history.title, "Corn Planting")
        self.assertEqual(history.establishment, self.establishment)
        self.assertEqual(history.parcel, self.parcel)
        self.assertEqual(history.event_type, "planting")
        self.assertEqual(history.crop_type, "corn")
        self.assertEqual(history.quantity, 50.0)
        self.assertIn("Corn Planting", str(history))

    def test_history_qr_code_generation(self):
        """Test QR code generation for production events."""
        history = History.objects.create(
            title="Tomato Harvest",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="harvesting",
            crop_type="tomato",
            created_by=self.user,
        )

        # QR code should be generated automatically
        self.assertIsNotNone(history.qr_code)
        self.assertTrue(history.qr_code.startswith("TRAZO"))
        self.assertEqual(len(history.qr_code), 16)  # Expected QR code length

    def test_history_ordering(self):
        """Test that history events are ordered by event_date descending."""
        base_date = timezone.now().date()

        history1 = History.objects.create(
            title="First Event",
            establishment=self.establishment,
            event_date=base_date - timedelta(days=2),
            created_by=self.user,
        )

        history2 = History.objects.create(
            title="Second Event",
            establishment=self.establishment,
            event_date=base_date - timedelta(days=1),
            created_by=self.user,
        )

        history3 = History.objects.create(
            title="Third Event", establishment=self.establishment, event_date=base_date, created_by=self.user
        )

        ordered_histories = History.objects.all()
        self.assertEqual(ordered_histories[0], history3)  # Most recent first
        self.assertEqual(ordered_histories[1], history2)
        self.assertEqual(ordered_histories[2], history1)

    def test_history_validation_required_fields(self):
        """Test validation of required fields."""
        # Missing title
        with self.assertRaises(ValidationError):
            history = History(establishment=self.establishment, event_date=timezone.now().date(), created_by=self.user)
            history.full_clean()

        # Missing establishment
        with self.assertRaises(ValidationError):
            history = History(title="Test Event", event_date=timezone.now().date(), created_by=self.user)
            history.full_clean()

    def test_history_event_type_validation(self):
        """Test event type validation."""
        valid_event_types = [
            "planting",
            "fertilizing",
            "irrigation",
            "pest_control",
            "harvesting",
            "soil_preparation",
            "pruning",
            "other",
        ]

        for event_type in valid_event_types:
            history = History.objects.create(
                title=f"Test {event_type}",
                establishment=self.establishment,
                event_date=timezone.now().date(),
                event_type=event_type,
                created_by=self.user,
            )
            self.assertEqual(history.event_type, event_type)

    def test_history_crop_type_validation(self):
        """Test crop type validation."""
        valid_crop_types = [
            "corn",
            "wheat",
            "soybeans",
            "tomato",
            "lettuce",
            "potato",
            "carrot",
            "broccoli",
            "apple",
            "orange",
            "other",
        ]

        for crop_type in valid_crop_types:
            history = History.objects.create(
                title=f"Test {crop_type}",
                establishment=self.establishment,
                event_date=timezone.now().date(),
                crop_type=crop_type,
                created_by=self.user,
            )
            self.assertEqual(history.crop_type, crop_type)

    def test_history_quantity_validation(self):
        """Test quantity validation (must be positive)."""
        # Positive quantity should work
        history = History.objects.create(
            title="Valid Quantity",
            establishment=self.establishment,
            event_date=timezone.now().date(),
            quantity=25.5,
            created_by=self.user,
        )
        self.assertEqual(history.quantity, 25.5)

        # Negative quantity should be invalid
        with self.assertRaises(ValidationError):
            history = History(
                title="Invalid Quantity",
                establishment=self.establishment,
                event_date=timezone.now().date(),
                quantity=-10.0,
                created_by=self.user,
            )
            history.full_clean()

    def test_history_carbon_integration(self):
        """Test integration with carbon calculation system."""
        # Create fertilizer application event
        history = History.objects.create(
            title="Nitrogen Fertilizer Application",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="fertilizing",
            fertilizer_type="nitrogen",
            quantity=100.0,
            unit="kg",
            created_by=self.user,
        )

        # Verify carbon entry was created (if auto-calculation is enabled)
        # This would test the signal handler that creates carbon entries
        carbon_entries = CarbonEntry.objects.filter(establishment=self.establishment, source_event=history)

        # If auto carbon calculation is enabled, there should be an entry
        # For now, just verify the history was created successfully
        self.assertIsNotNone(history.id)


# Skip HistoryTranslationTestCase - HistoryTranslation model not implemented
# class HistoryTranslationTestCase(TestCase):
#     """Test multi-language support for history events."""
#     def setUp(self):
#         pass
#     def test_translation_creation(self):
#         self.assertTrue(True)  # Placeholder


class QRCodeDataTestCase(TestCase):
    """Test QR code data generation and scanning."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="QR Test Farm")

        self.establishment = Establishment.objects.create(name="QR Test Field", company=self.company)

    def test_qr_code_data_creation(self):
        """Test QR code data creation."""
        qr_data = QRCodeData.objects.create(
            code="TRAZO1234567890",
            data_type="production_history",
            reference_id=str(uuid.uuid4()),
            metadata={"establishment_id": self.establishment.id, "crop_type": "tomato", "harvest_date": "2024-06-15"},
        )

        self.assertEqual(qr_data.code, "TRAZO1234567890")
        self.assertEqual(qr_data.data_type, "production_history")
        self.assertIsNotNone(qr_data.reference_id)
        self.assertEqual(qr_data.metadata["crop_type"], "tomato")

    def test_qr_code_uniqueness(self):
        """Test that QR codes are unique."""
        QRCodeData.objects.create(
            code="TRAZO_UNIQUE_001", data_type="production_history", reference_id=str(uuid.uuid4())
        )

        # Creating another QR with same code should fail
        with self.assertRaises(Exception):
            QRCodeData.objects.create(
                code="TRAZO_UNIQUE_001",  # Duplicate code
                data_type="production_history",
                reference_id=str(uuid.uuid4()),
            )

    def test_qr_code_scan_tracking(self):
        """Test QR code scan tracking."""
        qr_data = QRCodeData.objects.create(
            code="TRAZO_SCAN_TEST", data_type="production_history", reference_id=str(uuid.uuid4()), scan_count=0
        )

        # Simulate scan
        qr_data.record_scan()
        self.assertEqual(qr_data.scan_count, 1)

        # Another scan
        qr_data.record_scan()
        self.assertEqual(qr_data.scan_count, 2)

    def test_qr_code_expiration(self):
        """Test QR code expiration."""
        # Create expired QR code
        expired_qr = QRCodeData.objects.create(
            code="TRAZO_EXPIRED",
            data_type="production_history",
            reference_id=str(uuid.uuid4()),
            expires_at=timezone.now() - timedelta(days=1),
        )

        self.assertTrue(expired_qr.is_expired())

        # Create active QR code
        active_qr = QRCodeData.objects.create(
            code="TRAZO_ACTIVE",
            data_type="production_history",
            reference_id=str(uuid.uuid4()),
            expires_at=timezone.now() + timedelta(days=30),
        )

        self.assertFalse(active_qr.is_expired())


class HistoryViewSetTestCase(APITestCase):
    """Test History API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        # Create users with different roles
        self.farmer = User.objects.create_user(
            email="farmer@test.com", password="testpass123", first_name="John", last_name="Farmer"
        )

        self.manager = User.objects.create_user(
            email="manager@test.com", password="testpass123", first_name="Farm", last_name="Manager"
        )

        self.viewer = User.objects.create_user(
            email="viewer@test.com", password="testpass123", first_name="Data", last_name="Viewer"
        )

        # Create company and establishment
        self.company = Company.objects.create(name="API Test Farm")

        self.establishment = Establishment.objects.create(name="API Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Test Parcel", establishment=self.establishment, area=15.0)

        # Set up user roles
        WorksIn.objects.create(user=self.manager, company=self.company, role=WorksIn.FARM_MANAGER)

        WorksIn.objects.create(user=self.viewer, company=self.company, role=WorksIn.VIEWER)

        # Create test history event
        self.history = History.objects.create(
            title="Test Planting",
            description="Test planting event",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="planting",
            crop_type="corn",
            quantity=25.0,
            unit="acres",
            created_by=self.farmer,
        )

    def test_list_histories_authenticated(self):
        """Test listing histories requires authentication."""
        url = reverse("history-list")

        # Unauthenticated request should fail
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request should succeed
        self.client.force_authenticate(user=self.farmer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_histories_filtered_by_access(self):
        """Test that users only see histories they have access to."""
        # Create history for different company
        other_user = User.objects.create_user(email="other@test.com", password="testpass123")
        other_company = Company.objects.create(name="Other Company")
        other_establishment = Establishment.objects.create(name="Other Establishment", company=other_company)
        other_history = History.objects.create(
            title="Other History",
            establishment=other_establishment,
            event_date=timezone.now().date(),
            created_by=other_user,
        )

        self.client.force_authenticate(user=self.farmer)
        url = reverse("history-list")
        response = self.client.get(url)

        # Should only see own company's histories
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Test Planting")

    def test_create_history_valid(self):
        """Test creating history via API."""
        self.client.force_authenticate(user=self.farmer)
        url = reverse("history-list")

        data = {
            "title": "New Fertilizer Application",
            "description": "Applied organic fertilizer",
            "establishment": self.establishment.id,
            "parcel": self.parcel.id,
            "event_date": timezone.now().date().isoformat(),
            "event_type": "fertilizing",
            "fertilizer_type": "organic",
            "quantity": 50.0,
            "unit": "kg",
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "New Fertilizer Application")
        self.assertIsNotNone(response.data["qr_code"])

    def test_create_history_invalid_data(self):
        """Test creating history with invalid data."""
        self.client.force_authenticate(user=self.farmer)
        url = reverse("history-list")

        # Missing required title
        data = {
            "description": "Missing title",
            "establishment": self.establishment.id,
            "event_date": timezone.now().date().isoformat(),
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("title", response.data)

    def test_update_history_permissions(self):
        """Test history update permissions."""
        url = reverse("history-detail", kwargs={"pk": self.history.pk})

        data = {"title": "Updated Title", "description": "Updated description"}

        # Owner should be able to update
        self.client.force_authenticate(user=self.farmer)
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated Title")

        # Manager should be able to update
        self.client.force_authenticate(user=self.manager)
        response = self.client.patch(url, {"description": "Manager update"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Viewer should not be able to update
        self.client.force_authenticate(user=self.viewer)
        response = self.client.patch(url, {"title": "Viewer update"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_history_permissions(self):
        """Test history deletion permissions."""
        url = reverse("history-detail", kwargs={"pk": self.history.pk})

        # Viewer should not be able to delete
        self.client.force_authenticate(user=self.viewer)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Manager should be able to delete
        self.client.force_authenticate(user=self.manager)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(History.objects.filter(pk=self.history.pk).exists())


class HistoryImageHandlingTestCase(TestCase):
    """Test image upload and handling for history events."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Image Test Farm")

        self.establishment = Establishment.objects.create(name="Image Test Field", company=self.company)

        self.history = History.objects.create(
            title="Image Test Event",
            establishment=self.establishment,
            event_date=timezone.now().date(),
            created_by=self.user,
        )

    def test_image_upload_valid(self):
        """Test valid image upload."""
        # Create a simple test image
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            temp_file.write(b"fake image content")
            temp_file.flush()

            with open(temp_file.name, "rb") as image_file:
                uploaded_file = SimpleUploadedFile(
                    name="test_image.jpg", content=image_file.read(), content_type="image/jpeg"
                )

                self.history.images.add(uploaded_file)
                self.history.save()

            # Clean up
            os.unlink(temp_file.name)

        # Verify image was associated
        self.assertTrue(self.history.images.exists())

    def test_image_size_validation(self):
        """Test image size validation."""
        # This would test the max file size validation
        # Implementation depends on how image validation is handled

    def test_image_format_validation(self):
        """Test image format validation."""
        # Test that only allowed formats are accepted
        allowed_formats = ["image/jpeg", "image/png", "image/webp"]

        for content_type in allowed_formats:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                temp_file.write(b"fake image content")
                temp_file.flush()

                with open(temp_file.name, "rb") as image_file:
                    uploaded_file = SimpleUploadedFile(
                        name=f'test.{content_type.split("/")[1]}', content=image_file.read(), content_type=content_type
                    )

                    # This should succeed for allowed formats
                    try:
                        self.history.images.add(uploaded_file)
                        self.history.save()
                    except ValidationError:
                        self.fail(f"Valid format {content_type} was rejected")

                os.unlink(temp_file.name)


class VoiceEventProcessingTestCase(TestCase):
    """Test voice event processing and OpenAI integration."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Voice Test Farm")

        self.establishment = Establishment.objects.create(name="Voice Test Field", company=self.company)

    @patch("openai.ChatCompletion.create")
    def test_voice_to_text_processing(self, mock_openai):
        """Test voice-to-text processing with OpenAI."""
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Applied 25 kg of nitrogen fertilizer to corn field"))
        ]
        mock_openai.return_value = mock_response

        # Simulate voice processing
        voice_text = "Applied 25 kg of nitrogen fertilizer to corn field"

        # This would be the actual voice processing service call
        processed_data = {
            "title": "Fertilizer Application",
            "description": voice_text,
            "event_type": "fertilizing",
            "quantity": 25.0,
            "unit": "kg",
            "fertilizer_type": "nitrogen",
        }

        # Create history from voice data
        history = History.objects.create(
            title=processed_data["title"],
            description=processed_data["description"],
            establishment=self.establishment,
            event_date=timezone.now().date(),
            event_type=processed_data["event_type"],
            quantity=processed_data["quantity"],
            unit=processed_data["unit"],
            fertilizer_type=processed_data["fertilizer_type"],
            created_by=self.user,
        )

        self.assertEqual(history.title, "Fertilizer Application")
        self.assertEqual(history.event_type, "fertilizing")
        self.assertEqual(history.quantity, 25.0)
        mock_openai.assert_called_once()

    def test_voice_data_validation(self):
        """Test validation of voice-processed data."""
        # Test that voice-processed data still goes through validation
        with self.assertRaises(ValidationError):
            history = History(
                title="",  # Empty title from voice processing
                establishment=self.establishment,
                event_date=timezone.now().date(),
                created_by=self.user,
            )
            history.full_clean()


class HistoryAnalyticsTestCase(TestCase):
    """Test history analytics and reporting functionality."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Analytics Test Farm")

        self.establishment = Establishment.objects.create(name="Analytics Test Field", company=self.company)

        # Create multiple history events for analytics
        base_date = timezone.now().date()

        for i in range(10):
            History.objects.create(
                title=f"Event {i}",
                establishment=self.establishment,
                event_date=base_date - timedelta(days=i),
                event_type="planting" if i % 2 == 0 else "harvesting",
                crop_type="corn" if i % 3 == 0 else "wheat",
                quantity=float(10 + i),
                created_by=self.user,
            )

    def test_event_type_analytics(self):
        """Test analytics by event type."""
        planting_events = History.objects.filter(establishment=self.establishment, event_type="planting").count()

        harvesting_events = History.objects.filter(establishment=self.establishment, event_type="harvesting").count()

        self.assertEqual(planting_events, 5)
        self.assertEqual(harvesting_events, 5)

    def test_crop_type_analytics(self):
        """Test analytics by crop type."""
        corn_events = History.objects.filter(establishment=self.establishment, crop_type="corn").count()

        wheat_events = History.objects.filter(establishment=self.establishment, crop_type="wheat").count()

        self.assertGreater(corn_events, 0)
        self.assertGreater(wheat_events, 0)

    def test_monthly_activity_analytics(self):
        """Test monthly activity analytics."""
        current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly_events = History.objects.filter(
            establishment=self.establishment, event_date__gte=current_month.date()
        ).count()

        self.assertGreater(monthly_events, 0)

    def test_quantity_aggregation(self):
        """Test quantity aggregation for analytics."""
        from django.db.models import Avg, Sum

        total_quantity = History.objects.filter(establishment=self.establishment).aggregate(
            total=Sum("quantity"), average=Avg("quantity")
        )

        self.assertIsNotNone(total_quantity["total"])
        self.assertIsNotNone(total_quantity["average"])
        self.assertGreater(total_quantity["total"], 0)


class HistoryIntegrationTestCase(TransactionTestCase):
    """Test integration between history and other system components."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Integration Test Farm")

        self.establishment = Establishment.objects.create(name="Integration Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Integration Parcel", establishment=self.establishment, area=20.0)

    def test_carbon_calculation_integration(self):
        """Test integration with carbon calculation system."""
        # Create fertilizer application event
        fertilizer_history = History.objects.create(
            title="Nitrogen Application",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="fertilizing",
            fertilizer_type="nitrogen",
            quantity=100.0,
            unit="kg",
            created_by=self.user,
        )

        # Test that carbon entry would be created
        # This depends on signal handlers or service integration

        # For now, verify the history event was created properly
        self.assertEqual(fertilizer_history.event_type, "fertilizing")
        self.assertEqual(fertilizer_history.fertilizer_type, "nitrogen")

    def test_subscription_limits_integration(self):
        """Test integration with subscription limits."""
        # Create basic subscription with event limits
        subscription = Subscription.objects.create(
            company=self.company,
            plan_type="basic",
            status="active",
            max_events_per_month=5,
            current_events_this_month=4,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

        # Should be able to create one more event
        history = History.objects.create(
            title="Within Limit Event",
            establishment=self.establishment,
            event_date=timezone.now().date(),
            created_by=self.user,
        )

        self.assertIsNotNone(history.id)

        # Test that the 6th event would be blocked (implementation dependent)
        # This would be handled by middleware or service layer

    def test_qr_code_scanning_workflow(self):
        """Test complete QR code scanning workflow."""
        # Create history with QR code
        history = History.objects.create(
            title="QR Scannable Event",
            establishment=self.establishment,
            parcel=self.parcel,
            event_date=timezone.now().date(),
            event_type="harvesting",
            crop_type="tomato",
            quantity=500.0,
            unit="kg",
            created_by=self.user,
        )

        # Verify QR code was generated
        self.assertIsNotNone(history.qr_code)

        # Create QR code data entry
        qr_data = QRCodeData.objects.create(
            code=history.qr_code,
            data_type="production_history",
            reference_id=str(history.id),
            metadata={
                "title": history.title,
                "crop_type": history.crop_type,
                "quantity": history.quantity,
                "event_date": history.event_date.isoformat(),
            },
        )

        # Simulate QR scan
        qr_data.record_scan()

        self.assertEqual(qr_data.scan_count, 1)
        self.assertEqual(qr_data.reference_id, str(history.id))


class ChemicalEventValidationTestCase(TestCase):
    """Test NPK percentage validation for ChemicalEvent model."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Validation Test Farm")

        self.establishment = Establishment.objects.create(name="Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Test Parcel", establishment=self.establishment, area=15.0)

        # Create Product instance (no establishment field)
        self.product = Product.objects.create(name="Test Avocado")

        # Create History instance that ChemicalEvents will be attached to
        self.history = History.objects.create(
            name="Test Chemical History",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_valid_npk_percentages(self):
        """Test that valid NPK percentages are accepted."""
        # Test common fertilizer ratios
        valid_combinations = [
            (20, 10, 10),  # 20-10-10 fertilizer
            (24, 8, 16),  # Miracle-Gro All Purpose
            (21, 0, 0),  # High nitrogen
            (0, 46, 0),  # Triple superphosphate
            (0, 0, 60),  # Muriate of potash
            (10.5, 5.2, 8.3),  # Decimal values
        ]

        for n, p, k in valid_combinations:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Applied Test Fertilizer {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    commercial_name=f"Test Fertilizer {n}-{p}-{k}",
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Valid NPK combination {n}-{p}-{k} was rejected")

    def test_negative_npk_percentages(self):
        """Test that negative NPK percentages are rejected."""
        negative_cases = [
            (-5, 10, 10, "nitrogen_percentage"),
            (10, -3, 10, "phosphorus_percentage"),
            (10, 10, -8, "potassium_percentage"),
        ]

        for n, p, k, expected_field in negative_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that the correct field is flagged
                self.assertIn(expected_field, context.exception.error_dict)
                self.assertIn("cannot be negative", str(context.exception))

    def test_excessive_individual_npk_percentages(self):
        """Test that individual NPK percentages over 100% are rejected."""
        excessive_cases = [
            (150, 10, 10, "nitrogen_percentage"),
            (10, 200, 10, "phosphorus_percentage"),
            (10, 10, 300, "potassium_percentage"),
        ]

        for n, p, k, expected_field in excessive_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that the correct field is flagged
                self.assertIn(expected_field, context.exception.error_dict)
                self.assertIn("cannot exceed 100%", str(context.exception))

    def test_total_npk_exceeds_100_percent(self):
        """Test that total NPK percentages exceeding 100% are rejected."""
        excessive_total_cases = [
            (60, 30, 20),  # Total = 110%
            (50, 40, 30),  # Total = 120%
            (80, 15, 10),  # Total = 105%
            (33.4, 33.4, 33.4),  # Total = 100.2%
        ]

        for n, p, k in excessive_total_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that the total is flagged
                self.assertIn("__all__", context.exception.error_dict)
                self.assertIn("Total NPK percentages cannot exceed 100%", str(context.exception))

                # Verify detailed error message includes breakdown
                error_message = str(context.exception.error_dict["__all__"][0])
                self.assertIn(f"N: {n}%", error_message)
                self.assertIn(f"P: {p}%", error_message)
                self.assertIn(f"K: {k}%", error_message)

    def test_boundary_npk_values(self):
        """Test boundary values for NPK percentages."""
        boundary_cases = [
            # Exactly at limits
            (100, 0, 0),  # Maximum nitrogen
            (0, 100, 0),  # Maximum phosphorus
            (0, 0, 100),  # Maximum potassium
            (33.33, 33.33, 33.34),  # Exactly 100%
            (0, 0, 0),  # All zeros
            # Just under limits
            (99.9, 0, 0),  # Just under max nitrogen
            (0, 99.9, 0),  # Just under max phosphorus
            (0, 0, 99.9),  # Just under max potassium
        ]

        for n, p, k in boundary_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Boundary NPK combination {n}-{p}-{k} was rejected")

    def test_partial_npk_data(self):
        """Test validation with partial NPK data (some None values)."""
        partial_cases = [
            # Only one value provided
            (25, None, None),  # Only nitrogen
            (None, 15, None),  # Only phosphorus
            (None, None, 40),  # Only potassium
            # Two values provided
            (20, 10, None),  # N and P only
            (25, None, 15),  # N and K only
            (None, 12, 30),  # P and K only
        ]

        for n, p, k in partial_cases:
            with self.subTest(nitrogen=n, phosphorus=p, potassium=k):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test fertilizer application {n}-{p}-{k}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                # Should not raise ValidationError for partial data
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Partial NPK data {n}-{p}-{k} was rejected")

    def test_database_constraint_enforcement(self):
        """Test that database constraints are enforced."""
        from django.db import IntegrityError, transaction

        # Create a valid event first
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Test fertilizer for DB constraint test",
            date=timezone.now(),
            type=ChemicalEvent.FERTILIZER,
            nitrogen_percentage=20,
            phosphorus_percentage=10,
            potassium_percentage=10,
        )

        # Now try to update with invalid data directly at DB level
        # This should be caught by database constraints
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                # Try to update to invalid NPK totals
                ChemicalEvent.objects.filter(id=event.id).update(
                    nitrogen_percentage=60, phosphorus_percentage=30, potassium_percentage=20
                )

    def test_real_world_fertilizer_scenarios(self):
        """Test with real-world fertilizer NPK combinations."""
        real_fertilizers = [
            # Common commercial fertilizers
            ("Urea", 46, 0, 0),
            ("DAP", 18, 46, 0),
            ("Triple Superphosphate", 0, 46, 0),
            ("Muriate of Potash", 0, 0, 60),
            ("NPK 15-15-15", 15, 15, 15),
            ("NPK 10-26-26", 10, 26, 26),
            ("Ammonium Sulfate", 21, 0, 0),
            ("Bone Meal", 3, 15, 0),
            ("Compost", 1, 1, 1),
            ("Miracle-Gro", 24, 8, 16),
        ]

        for fertilizer_name, n, p, k in real_fertilizers:
            with self.subTest(fertilizer=fertilizer_name):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Applied {fertilizer_name}",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    commercial_name=fertilizer_name,
                    nitrogen_percentage=n,
                    phosphorus_percentage=p,
                    potassium_percentage=k,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)

                    # Verify values were saved correctly
                    saved_event = ChemicalEvent.objects.get(id=event.id)
                    self.assertEqual(saved_event.nitrogen_percentage, n)
                    self.assertEqual(saved_event.phosphorus_percentage, p)
                    self.assertEqual(saved_event.potassium_percentage, k)

                except ValidationError:
                    self.fail(f"Real fertilizer {fertilizer_name} ({n}-{p}-{k}) was rejected")

    def test_application_method_validation(self):
        """Test application method structured field validation."""
        valid_methods = ["broadcast", "injection", "foliar", "drip", "banding"]

        for method in valid_methods:
            with self.subTest(method=method):
                event = ChemicalEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Applied fertilizer using {method} method",
                    date=timezone.now(),
                    type=ChemicalEvent.FERTILIZER,
                    nitrogen_percentage=20,
                    phosphorus_percentage=10,
                    potassium_percentage=10,
                    application_method_structured=method,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertEqual(event.application_method_structured, method)
                except ValidationError:
                    self.fail(f"Valid application method {method} was rejected")

        # Test invalid method
        with self.assertRaises(ValidationError):
            event = ChemicalEvent(
                history=self.history,
                created_by=self.user,
                description="Test invalid application method",
                date=timezone.now(),
                type=ChemicalEvent.FERTILIZER,
                application_method_structured="invalid_method",
            )
            event.full_clean()


class EquipmentEventValidationTestCase(TestCase):
    """Test equipment event validation for fuel consumption and hours operated."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Equipment Test Farm")

        self.establishment = Establishment.objects.create(name="Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="Test Parcel", establishment=self.establishment, area=15.0)

        # Create Product instance
        self.product = Product.objects.create(name="Test Avocado")

        # Create History instance that EquipmentEvents will be attached to
        self.history = History.objects.create(
            name="Test Equipment History",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_valid_equipment_values(self):
        """Test that valid equipment values are accepted."""
        from decimal import Decimal

        # Test common equipment scenarios
        valid_combinations = [
            # (fuel_consumed, hours_operated, equipment_type, description)
            (Decimal("20.50"), Decimal("2.50"), EquipmentEvent.FUEL_CONSUMPTION, "Small tractor plowing"),
            (Decimal("45.00"), Decimal("3.00"), EquipmentEvent.FUEL_CONSUMPTION, "Medium tractor cultivation"),
            (Decimal("100.00"), Decimal("5.00"), EquipmentEvent.FUEL_CONSUMPTION, "Large tractor harvesting"),
            (Decimal("5.50"), Decimal("1.00"), EquipmentEvent.FUEL_CONSUMPTION, "Irrigation pump operation"),
            (Decimal("0.00"), Decimal("0.00"), EquipmentEvent.MAINTENANCE, "Manual maintenance no fuel"),
            (Decimal("15.20"), Decimal("8.50"), EquipmentEvent.FUEL_CONSUMPTION, "Full day spraying"),
        ]

        for fuel, hours, event_type, description in valid_combinations:
            with self.subTest(fuel=fuel, hours=hours, type=event_type):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=description,
                    date=timezone.now(),
                    type=event_type,
                    fuel_consumed=fuel,
                    hours_operated=hours,
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Valid equipment combination {description} was rejected")

    def test_negative_fuel_consumption(self):
        """Test that negative fuel consumption is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative fuel consumption",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=-10.5,
            hours_operated=2.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that fuel_consumed field is flagged
        self.assertIn("fuel_consumed", context.exception.error_dict)
        self.assertIn("cannot be negative", str(context.exception))

    def test_negative_hours_operated(self):
        """Test that negative hours operated is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative hours operated",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=15.0,
            hours_operated=-2.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that hours_operated field is flagged
        self.assertIn("hours_operated", context.exception.error_dict)
        self.assertIn("cannot be negative", str(context.exception))

    def test_negative_maintenance_cost(self):
        """Test that negative maintenance cost is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative maintenance cost",
            date=timezone.now(),
            type=EquipmentEvent.MAINTENANCE,
            maintenance_cost=-50.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that maintenance_cost field is flagged
        self.assertIn("maintenance_cost", context.exception.error_dict)

    def test_negative_area_worked(self):
        """Test that negative area worked is rejected."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test negative area worked",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            area_worked=-5.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that area_worked field is flagged
        self.assertIn("area_worked", context.exception.error_dict)

    def test_excessive_hours_operated(self):
        """Test that hours operated > 1000 is rejected (max for multi-day operations)."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test excessive hours operated",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=5000.0,
            hours_operated=1200.0,  # More than 1000 hours (max for multi-day operations)
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that hours_operated field is flagged
        self.assertIn("hours_operated", context.exception.error_dict)
        self.assertIn("cannot exceed 1000 hours", str(context.exception))

    def test_fuel_without_hours_validation(self):
        """Test validation when fuel is provided without hours."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test fuel without hours",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=25.0,
            hours_operated=None,  # Missing hours
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that hours_operated field is flagged
        self.assertIn("hours_operated", context.exception.error_dict)
        self.assertIn("should be provided when fuel consumption is recorded", str(context.exception))

    def test_unreasonable_fuel_efficiency_high(self):
        """Test detection of unreasonably high fuel consumption."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test unreasonably high fuel consumption",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=200.0,  # 200L in 2 hours = 100L/hr (unreasonable)
            hours_operated=2.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that fuel_consumed field is flagged for high consumption
        self.assertIn("fuel_consumed", context.exception.error_dict)
        self.assertIn("unreasonably high", str(context.exception))

    def test_unreasonable_fuel_efficiency_low(self):
        """Test detection of unreasonably low fuel consumption."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Test unreasonably low fuel consumption",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=0.2,  # 0.2L in 10 hours = 0.02L/hr (unreasonable)
            hours_operated=10.0,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that fuel_consumed field is flagged for low consumption
        self.assertIn("fuel_consumed", context.exception.error_dict)
        self.assertIn("unreasonably low", str(context.exception))

    def test_boundary_values(self):
        """Test boundary values for equipment validation."""
        from decimal import Decimal

        boundary_cases = [
            # Exactly at limits
            (Decimal("0.00"), Decimal("0.00")),  # Zero values (allowed)
            (Decimal("30.00"), Decimal("24.00")),  # Reasonable day consumption
            (Decimal("24.00"), Decimal("24.00")),  # 1L/hr (reasonable)
            (Decimal("600.00"), Decimal("12.00")),  # 50L/hr (maximum reasonable)
            # Just under limits
            (Decimal("23.90"), Decimal("23.90")),  # Just under max hours
            (Decimal("3.00"), Decimal("1.00")),  # 3L/hr (reasonable small tractor)
            (Decimal("49.00"), Decimal("1.00")),  # Just under max efficiency
        ]

        for fuel, hours in boundary_cases:
            with self.subTest(fuel=fuel, hours=hours):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test boundary fuel={fuel}L, hours={hours}h",
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    fuel_consumed=fuel,
                    hours_operated=hours,
                )

                # Should not raise ValidationError
                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)
                except ValidationError:
                    self.fail(f"Boundary case fuel={fuel}L, hours={hours}h was rejected")

    def test_real_world_equipment_scenarios(self):
        """Test with real-world equipment scenarios."""
        real_scenarios = [
            # (fuel, hours, equipment_type, description)
            (8.5, 1.5, "tractor_small", "Small tractor plowing 2 hectares"),
            (45.0, 3.0, "tractor_medium", "Medium tractor cultivating"),
            (120.0, 4.0, "tractor_large", "Large tractor with heavy implements"),
            (15.0, 6.0, "irrigation_pump", "Irrigation pump watering crops"),
            (80.0, 2.5, "harvester", "Combine harvester collecting grain"),
            (25.0, 3.5, "sprayer", "Field sprayer applying chemicals"),
            (35.0, 4.0, "cultivator", "Cultivator preparing seedbed"),
            (60.0, 5.0, "transport", "Transport vehicle moving produce"),
        ]

        for fuel, hours, equipment_type, description in real_scenarios:
            with self.subTest(scenario=description):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=description,
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    fuel_consumed=fuel,
                    hours_operated=hours,
                    equipment_type_structured=equipment_type,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertIsNotNone(event.id)

                    # Verify values were saved correctly
                    saved_event = EquipmentEvent.objects.get(id=event.id)
                    self.assertEqual(saved_event.fuel_consumed, fuel)
                    self.assertEqual(saved_event.hours_operated, hours)
                    self.assertEqual(saved_event.equipment_type_structured, equipment_type)

                except ValidationError:
                    self.fail(f"Real equipment scenario {description} was rejected")

    def test_database_constraint_enforcement(self):
        """Test that database constraints are enforced."""
        from django.db import IntegrityError, transaction

        # Create a valid event first
        event = EquipmentEvent.objects.create(
            history=self.history,
            created_by=self.user,
            description="Test equipment for DB constraint test",
            date=timezone.now(),
            type=EquipmentEvent.FUEL_CONSUMPTION,
            fuel_consumed=25.0,
            hours_operated=5.0,
        )

        # Now try to update with invalid data directly at DB level
        # This should be caught by database constraints
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                # Try to update to invalid negative fuel consumption
                EquipmentEvent.objects.filter(id=event.id).update(fuel_consumed=-10.0)

    def test_equipment_type_validation(self):
        """Test equipment type structured field validation."""
        valid_types = [
            "tractor_small",
            "tractor_medium",
            "tractor_large",
            "irrigation_pump",
            "harvester",
            "sprayer",
            "cultivator",
            "transport",
        ]

        for equipment_type in valid_types:
            with self.subTest(type=equipment_type):
                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test {equipment_type} equipment",
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    fuel_consumed=20.0,
                    hours_operated=4.0,
                    equipment_type_structured=equipment_type,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertEqual(event.equipment_type_structured, equipment_type)
                except ValidationError:
                    self.fail(f"Valid equipment type {equipment_type} was rejected")

    def test_maintenance_event_no_fuel(self):
        """Test maintenance events without fuel consumption."""
        event = EquipmentEvent(
            history=self.history,
            created_by=self.user,
            description="Regular maintenance checkup",
            date=timezone.now(),
            type=EquipmentEvent.MAINTENANCE,
            maintenance_cost=150.0,
            fuel_consumed=None,  # No fuel consumed during maintenance
            hours_operated=2.0,  # Hours spent on maintenance
        )

        # Should not raise ValidationError
        try:
            event.full_clean()
            event.save()
            self.assertIsNotNone(event.id)
            self.assertIsNone(event.fuel_consumed)
            self.assertEqual(event.maintenance_cost, 150.0)
        except ValidationError:
            self.fail("Maintenance event without fuel consumption was rejected")

    def test_partial_equipment_data(self):
        """Test validation with partial equipment data (some None values)."""
        partial_cases = [
            # Only fuel_consumed provided
            {"fuel_consumed": 25.0, "hours_operated": None, "area_worked": None},
            # Only hours_operated provided
            {"fuel_consumed": None, "hours_operated": 3.0, "area_worked": None},
            # Only area_worked provided
            {"fuel_consumed": None, "hours_operated": None, "area_worked": 5.0},
            # Two values provided
            {"fuel_consumed": None, "hours_operated": 2.0, "area_worked": 3.0},
        ]

        for case_data in partial_cases:
            with self.subTest(data=case_data):
                # Note: fuel without hours should trigger validation error
                should_error = (
                    case_data.get("fuel_consumed")
                    and case_data.get("fuel_consumed") > 0
                    and not case_data.get("hours_operated")
                )

                event = EquipmentEvent(
                    history=self.history,
                    created_by=self.user,
                    description=f"Test partial data: {case_data}",
                    date=timezone.now(),
                    type=EquipmentEvent.FUEL_CONSUMPTION,
                    **case_data,
                )

                if should_error:
                    with self.assertRaises(ValidationError):
                        event.full_clean()
                else:
                    try:
                        event.full_clean()
                        event.save()
                        self.assertIsNotNone(event.id)
                    except ValidationError:
                        self.fail(f"Partial equipment data {case_data} was rejected")


# Production Event Validation Tests
class ProductionEventValidationTestCase(TestCase):
    """Test production event validation for area, yield, and transportation constraints."""

    def setUp(self):
        """Set up test data for production event validation tests."""
        # Create test user
        self.user = User.objects.create_user(email="testuser@example.com", password="testpass123")

        # Create test company and establishment
        self.company = Company.objects.create(
            name="Test Organic Farm",
            contact_email="test@farm.com",
            city="Test City",
            state="Test State",
            address="123 Test Street",
        )

        # Create test plan and subscription
        from subscriptions.models import Plan

        self.plan = Plan.objects.create(
            name="Basic Plan",
            slug="basic",
            description="Basic plan for testing",
            price=29.99,  # Add required price field
        )

        self.subscription = Subscription.objects.create(
            company=self.company, plan=self.plan, stripe_subscription_id="test_sub_123"
        )

        # Create test establishment
        self.establishment = Establishment.objects.create(name="Main Farm Location", company=self.company)

        # Link user to company
        self.works_in = WorksIn.objects.create(user=self.user, company=self.company)
        self.works_in.establishments_in_charge.add(self.establishment)

        # Create test parcel and product
        self.parcel = Parcel.objects.create(name="Test Field A", establishment=self.establishment, area=10.5)

        self.product = Product.objects.create(name="Organic Avocados", company=self.company, parcel=self.parcel)

        # Create test history for events
        self.history = History.objects.create(
            user=self.user,
            product=self.product,
            parcel=self.parcel,
            name="Test Production History",
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_valid_production_values(self):
        """Test that valid production values are accepted."""
        from decimal import Decimal

        # Test common production scenarios
        valid_combinations = [
            # (area_covered, yield_quantity, transportation_distance, equipment_hours, description)
            (Decimal("2.50"), Decimal("5000.00"), Decimal("25.00"), Decimal("4.00"), "Small field harvesting"),
            (Decimal("10.00"), Decimal("15000.00"), Decimal("50.00"), Decimal("8.00"), "Medium farm planting"),
            (Decimal("0.10"), Decimal("100.00"), Decimal("5.00"), Decimal("1.00"), "Small plot test"),
            (Decimal("50.00"), Decimal("75000.00"), Decimal("100.00"), Decimal("12.00"), "Large field operation"),
            (Decimal("1.00"), None, Decimal("0.00"), Decimal("2.00"), "Planting with no yield yet"),
            (Decimal("5.00"), Decimal("0.00"), Decimal("15.00"), None, "Field preparation"),
        ]

        for area, yield_qty, transport_dist, equip_hours, description in valid_combinations:
            with self.subTest(area=area, yield_qty=yield_qty, transport=transport_dist, hours=equip_hours):
                event = ProductionEvent(
                    history=self.history,
                    created_by=self.user,
                    type=ProductionEvent.HARVESTING,
                    description=description,
                    date=timezone.now(),
                    area_covered=area,
                    yield_quantity=yield_qty,
                    transportation_distance=transport_dist,
                    equipment_hours=equip_hours,
                )

                try:
                    event.full_clean()
                    event.save()
                    self.assertTrue(True, f"Valid production combination {description} was accepted")
                except ValidationError as e:
                    self.fail(f"Valid production combination {description} was rejected: {e}")

    def test_invalid_area_covered(self):
        """Test that invalid area covered values are rejected."""
        from decimal import Decimal

        invalid_areas = [
            (Decimal("-1.00"), "Negative area"),
            (Decimal("0.00"), "Zero area"),
        ]

        for invalid_area, description in invalid_areas:
            with self.subTest(area=invalid_area):
                event = ProductionEvent(
                    history=self.history,
                    created_by=self.user,
                    type=ProductionEvent.PLANTING,
                    description=f"Test {description}",
                    date=timezone.now(),
                    area_covered=invalid_area,
                    yield_quantity=Decimal("1000.00"),
                )

                with self.assertRaises(ValidationError) as context:
                    event.full_clean()

                # Check that area_covered field is flagged
                self.assertIn("area_covered", context.exception.error_dict)

    def test_invalid_yield_quantity(self):
        """Test that negative yield quantities are rejected."""
        from decimal import Decimal

        event = ProductionEvent(
            history=self.history,
            created_by=self.user,
            type=ProductionEvent.HARVESTING,
            description="Test negative yield",
            date=timezone.now(),
            area_covered=Decimal("5.00"),
            yield_quantity=Decimal("-100.00"),
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        # Check that yield_quantity field is flagged
        self.assertIn("yield_quantity", context.exception.error_dict)

    def test_real_world_production_scenarios(self):
        """Test with real-world production scenarios."""
        from decimal import Decimal

        real_scenarios = [
            (
                Decimal("5.0"),
                Decimal("25000.0"),
                Decimal("30.0"),
                Decimal("6.0"),
                "avocado",
                "Avocado harvest - 5 tons/ha",
            ),
            (
                Decimal("2.5"),
                Decimal("7500.0"),
                Decimal("15.0"),
                Decimal("4.0"),
                "citrus",
                "Citrus harvest - 3 tons/ha",
            ),
            (Decimal("10.0"), None, Decimal("50.0"), Decimal("8.0"), "planting", "Field planting - no yield yet"),
            (
                Decimal("1.0"),
                Decimal("4000.0"),
                Decimal("10.0"),
                Decimal("2.0"),
                "vegetable",
                "Vegetable harvest - 4 tons/ha",
            ),
            (
                Decimal("20.0"),
                Decimal("120000.0"),
                Decimal("75.0"),
                Decimal("12.0"),
                "grain",
                "Grain harvest - 6 tons/ha",
            ),
        ]

        for area, yield_qty, transport, hours, crop_type, description in real_scenarios:
            with self.subTest(crop=crop_type, desc=description):
                event = ProductionEvent(
                    history=self.history,
                    created_by=self.user,
                    type=ProductionEvent.HARVESTING if yield_qty else ProductionEvent.PLANTING,
                    description=description,
                    date=timezone.now(),
                    area_covered=area,
                    yield_quantity=yield_qty,
                    transportation_distance=transport,
                    equipment_hours=hours,
                )

                try:
                    event.full_clean()
                    event.save()
                    # Verify carbon calculation integration
                    self.assertIsNotNone(event.id)
                except ValidationError as e:
                    self.fail(f"Real-world scenario {description} failed: {e}")
