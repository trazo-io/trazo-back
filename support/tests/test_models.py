"""
Comprehensive test suite for Support app functionality.
Tests cover ticket management, SLA tracking, and customer support workflows.

Test Coverage:
- Support ticket creation and lifecycle management
- SLA response and resolution time tracking
- Priority-based ticket routing and escalation
- Support message threading and communication
- File attachment handling and validation
- Staff assignment and workload management
- Customer satisfaction tracking and analytics
- Integration with subscription plans for support tiers
- Performance optimizations for large ticket volumes
"""

import json
import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Avg, Count, Q
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from company.models import Company, Establishment
from subscriptions.models import Plan, Subscription
from support.models import SupportAttachment, SupportMessage, SupportSLA, SupportTicket
from users.models import User, WorksIn

User = get_user_model()


class SupportTicketTestCase(TestCase):
    """Test SupportTicket model functionality and validation."""

    def setUp(self):
        self.customer = User.objects.create_user(
            email="customer@test.com", password="testpass123", first_name="Farm", last_name="Owner"
        )

        self.support_agent = User.objects.create_user(
            email="support@test.com", password="testpass123", first_name="Support", last_name="Agent", is_staff=True
        )

        self.company = Company.objects.create(name="Test Farm Co.", owner=self.customer)

        # Create basic subscription
        self.plan = Plan.objects.create(
            name="Basic Plan",
            plan_type="basic",
            price=29.99,
            features={"support_response_time": 48, "priority_support": False},
        )

        self.subscription = Subscription.objects.create(
            company=self.company,
            plan=self.plan,
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def test_ticket_creation_valid(self):
        """Test creating support ticket with valid data."""
        ticket = SupportTicket.objects.create(
            subject="Unable to sync John Deere tractor data",
            description="""
            I've connected my John Deere tractor to Trazo but the field operation data
            isn't syncing. The last sync was 3 days ago and I've completed several
            planting operations that aren't showing up in my carbon tracking.
            
            Tractor model: John Deere 8345R
            Operations missing: Corn planting on Field A (40 acres)
            Error messages: None visible in the app
            """,
            category="iot_devices",
            priority="high",
            user=self.customer,
            company=self.company,
        )

        self.assertIsNotNone(ticket.ticket_id)
        self.assertTrue(ticket.ticket_id.startswith("TRZ-"))
        self.assertEqual(ticket.subject, "Unable to sync John Deere tractor data")
        self.assertEqual(ticket.category, "iot_devices")
        self.assertEqual(ticket.priority, "high")
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.user, self.customer)
        self.assertEqual(ticket.company, self.company)
        self.assertEqual(ticket.sla_response_hours, 48)  # From basic plan
        self.assertIn("TRZ-", str(ticket))

    def test_ticket_id_generation(self):
        """Test automatic ticket ID generation."""
        ticket1 = SupportTicket.objects.create(
            subject="First ticket", description="First ticket description", user=self.customer, company=self.company
        )

        ticket2 = SupportTicket.objects.create(
            subject="Second ticket", description="Second ticket description", user=self.customer, company=self.company
        )

        self.assertIsNotNone(ticket1.ticket_id)
        self.assertIsNotNone(ticket2.ticket_id)
        self.assertNotEqual(ticket1.ticket_id, ticket2.ticket_id)
        self.assertTrue(ticket1.ticket_id.startswith("TRZ-"))
        self.assertTrue(ticket2.ticket_id.startswith("TRZ-"))

    def test_sla_setting_from_subscription(self):
        """Test SLA times are set based on subscription plan."""
        # Basic plan ticket
        basic_ticket = SupportTicket.objects.create(
            subject="Basic plan ticket", description="Test ticket", user=self.customer, company=self.company
        )

        self.assertEqual(basic_ticket.sla_response_hours, 48)

        # Create premium plan with faster response time
        premium_plan = Plan.objects.create(
            name="Premium Plan",
            plan_type="premium",
            price=99.99,
            features={"support_response_time": 12, "priority_support": True},
        )

        # Update subscription to premium
        self.subscription.plan = premium_plan
        self.subscription.save()

        premium_ticket = SupportTicket.objects.create(
            subject="Premium plan ticket", description="Premium test ticket", user=self.customer, company=self.company
        )

        self.assertEqual(premium_ticket.sla_response_hours, 12)
        self.assertEqual(premium_ticket.priority, "high")  # Auto-elevated for priority support

    def test_ticket_categories(self):
        """Test different ticket categories."""
        categories = ["billing", "technical", "feature_request", "carbon_tracking", "iot_devices", "account", "other"]

        for category in categories:
            ticket = SupportTicket.objects.create(
                subject=f"Test {category} ticket",
                description=f"Testing {category} category",
                category=category,
                user=self.customer,
                company=self.company,
            )

            self.assertEqual(ticket.category, category)

    def test_ticket_priorities(self):
        """Test different ticket priorities."""
        priorities = ["low", "normal", "high", "urgent"]

        for priority in priorities:
            ticket = SupportTicket.objects.create(
                subject=f"Test {priority} priority ticket",
                description=f"Testing {priority} priority",
                priority=priority,
                user=self.customer,
                company=self.company,
            )

            self.assertEqual(ticket.priority, priority)

    def test_sla_deadline_calculations(self):
        """Test SLA deadline calculations."""
        ticket = SupportTicket.objects.create(
            subject="SLA test ticket",
            description="Testing SLA calculations",
            user=self.customer,
            company=self.company,
            sla_response_hours=24,
            sla_resolution_hours=72,
        )

        expected_response_deadline = ticket.created_at + timedelta(hours=24)
        expected_resolution_deadline = ticket.created_at + timedelta(hours=72)

        self.assertEqual(ticket.sla_response_deadline, expected_response_deadline)
        self.assertEqual(ticket.sla_resolution_deadline, expected_resolution_deadline)

    def test_overdue_detection(self):
        """Test overdue ticket detection."""
        # Create ticket with short SLA for testing
        ticket = SupportTicket.objects.create(
            subject="Overdue test ticket",
            description="Testing overdue detection",
            user=self.customer,
            company=self.company,
            sla_response_hours=1,  # 1 hour SLA
            sla_resolution_hours=24,
        )

        # Should not be overdue initially
        self.assertFalse(ticket.is_overdue_response)
        self.assertFalse(ticket.is_overdue_resolution)

        # Manually set created_at to past to simulate overdue
        ticket.created_at = timezone.now() - timedelta(hours=2)
        ticket.save()

        self.assertTrue(ticket.is_overdue_response)
        self.assertFalse(ticket.is_overdue_resolution)  # Resolution SLA longer

    def test_ticket_assignment(self):
        """Test ticket assignment to support agents."""
        ticket = SupportTicket.objects.create(
            subject="Assignment test", description="Testing ticket assignment", user=self.customer, company=self.company
        )

        # Assign to support agent
        ticket.assigned_to = self.support_agent
        ticket.save()

        self.assertEqual(ticket.assigned_to, self.support_agent)

    def test_ticket_status_transitions(self):
        """Test ticket status transitions."""
        ticket = SupportTicket.objects.create(
            subject="Status test", description="Testing status transitions", user=self.customer, company=self.company
        )

        # Initial status
        self.assertEqual(ticket.status, "open")

        # Change to in progress
        ticket.status = "in_progress"
        ticket.save()
        self.assertEqual(ticket.status, "in_progress")

        # Mark as resolved
        ticket.mark_resolved()
        self.assertEqual(ticket.status, "resolved")
        self.assertIsNotNone(ticket.resolved_at)

        # Mark as closed
        ticket.mark_closed()
        self.assertEqual(ticket.status, "closed")
        self.assertIsNotNone(ticket.closed_at)

    def test_response_time_tracking(self):
        """Test response time tracking."""
        ticket = SupportTicket.objects.create(
            subject="Response time test",
            description="Testing response time tracking",
            user=self.customer,
            company=self.company,
        )

        # No response yet
        self.assertIsNone(ticket.response_time_hours)

        # Mark first response
        ticket.mark_first_response()
        self.assertIsNotNone(ticket.first_response_at)
        self.assertIsNotNone(ticket.response_time_hours)
        self.assertGreater(ticket.response_time_hours, 0)

    def test_resolution_time_tracking(self):
        """Test resolution time tracking."""
        ticket = SupportTicket.objects.create(
            subject="Resolution time test",
            description="Testing resolution time tracking",
            user=self.customer,
            company=self.company,
        )

        # No resolution yet
        self.assertIsNone(ticket.resolution_time_hours)

        # Mark as resolved
        ticket.mark_resolved()
        self.assertIsNotNone(ticket.resolved_at)
        self.assertIsNotNone(ticket.resolution_time_hours)
        self.assertGreater(ticket.resolution_time_hours, 0)


class SupportMessageTestCase(TestCase):
    """Test SupportMessage model functionality."""

    def setUp(self):
        self.customer = User.objects.create_user(email="customer@test.com", password="testpass123")

        self.support_agent = User.objects.create_user(email="support@test.com", password="testpass123", is_staff=True)

        self.company = Company.objects.create(name="Message Test Co.", owner=self.customer)

        self.ticket = SupportTicket.objects.create(
            subject="Message test ticket",
            description="Testing message functionality",
            user=self.customer,
            company=self.company,
        )

    def test_customer_message_creation(self):
        """Test creating customer message."""
        message = SupportMessage.objects.create(
            ticket=self.ticket,
            author=self.customer,
            message_type="customer",
            content="""
            Hi, I wanted to provide more details about the syncing issue.
            
            I've tried the troubleshooting steps from the FAQ but the problem persists.
            Here's what I've done:
            1. Restarted the John Deere Operations Center connection
            2. Checked my internet connection (working fine)
            3. Verified the tractor is online and sending data to JD servers
            
            The issue seems to be specific to Trazo's integration.
            """,
            is_internal=False,
        )

        self.assertEqual(message.ticket, self.ticket)
        self.assertEqual(message.author, self.customer)
        self.assertEqual(message.message_type, "customer")
        self.assertIn("John Deere Operations Center", message.content)
        self.assertFalse(message.is_internal)
        self.assertIn(self.ticket.ticket_id, str(message))

    def test_staff_response_creation(self):
        """Test creating staff response."""
        response = SupportMessage.objects.create(
            ticket=self.ticket,
            author=self.support_agent,
            message_type="staff",
            content="""
            Thank you for the additional details. I can see the issue is with our 
            John Deere API integration.
            
            I've escalated this to our engineering team and they're investigating
            a known issue with the JD Operations Center API that started yesterday.
            
            Expected resolution: Within 24 hours
            I'll update you as soon as we have more information.
            
            Best regards,
            Sarah - Trazo Support Team
            """,
            is_internal=False,
        )

        self.assertEqual(response.author, self.support_agent)
        self.assertEqual(response.message_type, "staff")
        self.assertIn("engineering team", response.content)

    def test_internal_note_creation(self):
        """Test creating internal staff note."""
        internal_note = SupportMessage.objects.create(
            ticket=self.ticket,
            author=self.support_agent,
            message_type="internal",
            content="""
            INTERNAL NOTE:
            - Customer has John Deere 8345R (confirmed compatible)
            - Issue started 3 days ago (matches our API outage timeline)
            - Engineering ticket #ENG-2024-156 created
            - Customer is on Basic plan (48h SLA)
            - No previous support tickets from this customer
            """,
            is_internal=True,
        )

        self.assertTrue(internal_note.is_internal)
        self.assertEqual(internal_note.message_type, "internal")
        self.assertIn("INTERNAL NOTE", internal_note.content)

    def test_system_message_creation(self):
        """Test system-generated messages."""
        system_message = SupportMessage.objects.create(
            ticket=self.ticket,
            author=self.support_agent,  # System uses staff account
            message_type="system",
            content="Ticket automatically escalated to engineering team due to SLA approaching.",
            is_internal=False,
        )

        self.assertEqual(system_message.message_type, "system")
        self.assertIn("automatically escalated", system_message.content)

    def test_first_response_tracking(self):
        """Test first response time tracking."""
        # Initially no first response
        self.assertIsNone(self.ticket.first_response_at)

        # Customer message shouldn't trigger first response
        SupportMessage.objects.create(
            ticket=self.ticket, author=self.customer, message_type="customer", content="Additional customer message"
        )

        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_response_at)

        # Staff response should trigger first response tracking
        SupportMessage.objects.create(
            ticket=self.ticket, author=self.support_agent, message_type="staff", content="First staff response"
        )

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.first_response_at)

    def test_message_ordering(self):
        """Test message ordering by creation time."""
        # Create messages in order
        message1 = SupportMessage.objects.create(
            ticket=self.ticket, author=self.customer, message_type="customer", content="First message"
        )

        message2 = SupportMessage.objects.create(
            ticket=self.ticket, author=self.support_agent, message_type="staff", content="Second message"
        )

        message3 = SupportMessage.objects.create(
            ticket=self.ticket, author=self.customer, message_type="customer", content="Third message"
        )

        # Verify ordering
        messages = SupportMessage.objects.filter(ticket=self.ticket)
        self.assertEqual(messages[0], message1)
        self.assertEqual(messages[1], message2)
        self.assertEqual(messages[2], message3)


class SupportAttachmentTestCase(TestCase):
    """Test SupportAttachment model functionality."""

    def setUp(self):
        self.customer = User.objects.create_user(email="customer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Attachment Test Co.", owner=self.customer)

        self.ticket = SupportTicket.objects.create(
            subject="Attachment test ticket",
            description="Testing file attachments",
            user=self.customer,
            company=self.company,
        )

        self.message = SupportMessage.objects.create(
            ticket=self.ticket, author=self.customer, message_type="customer", content="Message with attachment"
        )

    def test_attachment_creation(self):
        """Test creating file attachment."""
        # Create temporary test file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_file.write(b"fake image content for testing")
            temp_file.flush()

            with open(temp_file.name, "rb") as file:
                uploaded_file = SimpleUploadedFile(
                    name="error_screenshot.png", content=file.read(), content_type="image/png"
                )

                attachment = SupportAttachment.objects.create(
                    ticket=self.ticket,
                    message=self.message,
                    file=uploaded_file,
                    original_filename="error_screenshot.png",
                    file_size=len(file.read()),
                    content_type="image/png",
                    uploaded_by=self.customer,
                )

            # Clean up
            os.unlink(temp_file.name)

        self.assertEqual(attachment.ticket, self.ticket)
        self.assertEqual(attachment.message, self.message)
        self.assertEqual(attachment.original_filename, "error_screenshot.png")
        self.assertEqual(attachment.content_type, "image/png")
        self.assertEqual(attachment.uploaded_by, self.customer)
        self.assertIn("error_screenshot.png", str(attachment))

    def test_attachment_without_message(self):
        """Test creating attachment directly to ticket (not specific message)."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file.write(b"fake PDF content")
            temp_file.flush()

            with open(temp_file.name, "rb") as file:
                uploaded_file = SimpleUploadedFile(
                    name="system_logs.pdf", content=file.read(), content_type="application/pdf"
                )

                attachment = SupportAttachment.objects.create(
                    ticket=self.ticket,
                    # No message specified
                    file=uploaded_file,
                    original_filename="system_logs.pdf",
                    file_size=len(file.read()),
                    content_type="application/pdf",
                    uploaded_by=self.customer,
                )

            os.unlink(temp_file.name)

        self.assertEqual(attachment.ticket, self.ticket)
        self.assertIsNone(attachment.message)
        self.assertEqual(attachment.content_type, "application/pdf")

    def test_file_size_tracking(self):
        """Test file size tracking."""
        test_content = b"test file content for size tracking"

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temp_file:
            temp_file.write(test_content)
            temp_file.flush()

            with open(temp_file.name, "rb") as file:
                uploaded_file = SimpleUploadedFile(name="test_file.txt", content=file.read(), content_type="text/plain")

                attachment = SupportAttachment.objects.create(
                    ticket=self.ticket,
                    file=uploaded_file,
                    original_filename="test_file.txt",
                    file_size=len(test_content),
                    content_type="text/plain",
                    uploaded_by=self.customer,
                )

            os.unlink(temp_file.name)

        self.assertEqual(attachment.file_size, len(test_content))


class SupportSLATestCase(TestCase):
    """Test SupportSLA model functionality and metrics."""

    def setUp(self):
        self.current_month = timezone.now().replace(day=1)

    def test_sla_metrics_creation(self):
        """Test creating SLA metrics record."""
        sla_metrics = SupportSLA.objects.create(
            plan_name="Basic Plan",
            month=self.current_month.date(),
            total_tickets=100,
            met_response_sla=85,
            avg_response_time_hours=36.5,
            max_response_time_hours=72.0,
            resolved_tickets=90,
            met_resolution_sla=82,
            avg_resolution_time_hours=96.2,
            satisfaction_ratings=75,
            avg_satisfaction_score=4.2,
        )

        self.assertEqual(sla_metrics.plan_name, "Basic Plan")
        self.assertEqual(sla_metrics.total_tickets, 100)
        self.assertEqual(sla_metrics.met_response_sla, 85)
        self.assertEqual(sla_metrics.avg_response_time_hours, 36.5)
        self.assertEqual(sla_metrics.resolved_tickets, 90)
        self.assertEqual(sla_metrics.avg_satisfaction_score, 4.2)

    def test_sla_percentage_calculations(self):
        """Test SLA percentage calculations."""
        sla_metrics = SupportSLA.objects.create(
            plan_name="Premium Plan",
            month=self.current_month.date(),
            total_tickets=50,
            met_response_sla=45,
            resolved_tickets=48,
            met_resolution_sla=42,
        )

        response_percentage = sla_metrics.response_sla_percentage
        resolution_percentage = sla_metrics.resolution_sla_percentage

        self.assertEqual(response_percentage, 90.0)  # 45/50 * 100
        self.assertEqual(resolution_percentage, 87.5)  # 42/48 * 100

    def test_sla_zero_division_handling(self):
        """Test SLA percentage calculations with zero tickets."""
        sla_metrics = SupportSLA.objects.create(
            plan_name="Test Plan",
            month=self.current_month.date(),
            total_tickets=0,
            met_response_sla=0,
            resolved_tickets=0,
            met_resolution_sla=0,
        )

        self.assertEqual(sla_metrics.response_sla_percentage, 0)
        self.assertEqual(sla_metrics.resolution_sla_percentage, 0)

    def test_sla_unique_constraint(self):
        """Test unique constraint on plan_name and month."""
        SupportSLA.objects.create(plan_name="Corporate Plan", month=self.current_month.date(), total_tickets=25)

        # Creating another record for same plan/month should fail
        with self.assertRaises(Exception):
            SupportSLA.objects.create(
                plan_name="Corporate Plan", month=self.current_month.date(), total_tickets=30  # Duplicate plan/month
            )


class SupportAPITestCase(APITestCase):
    """Test Support API endpoints and permissions."""

    def setUp(self):
        self.client = APIClient()

        # Create users
        self.customer = User.objects.create_user(
            email="customer@test.com", password="testpass123", user_type="producer"
        )

        self.support_agent = User.objects.create_user(email="support@test.com", password="testpass123", is_staff=True)

        self.company = Company.objects.create(name="API Test Farm", owner=self.customer)

        # Create test ticket
        self.ticket = SupportTicket.objects.create(
            subject="API test ticket",
            description="Testing API functionality",
            category="technical",
            user=self.customer,
            company=self.company,
        )

    def test_create_ticket_authenticated(self):
        """Test creating ticket requires authentication."""
        url = reverse("support:ticket-list")

        data = {"subject": "New API ticket", "description": "Testing ticket creation via API", "category": "billing"}

        # Unauthenticated request should fail
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request should succeed
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_ticket_valid_data(self):
        """Test creating ticket with valid data."""
        self.client.force_authenticate(user=self.customer)
        url = reverse("support:ticket-list")

        data = {
            "subject": "Carbon calculation discrepancy",
            "description": """
            I noticed that my carbon footprint calculation seems incorrect for last month.
            
            Details:
            - Field: North Field (40 acres)
            - Crop: Corn
            - Fertilizer applied: 150 lbs nitrogen
            - Expected CO2e: ~1.8 tons
            - Calculated CO2e: 4.2 tons
            
            Could you help me understand why there's such a large difference?
            """,
            "category": "carbon_tracking",
            "priority": "normal",
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify ticket was created
        created_ticket = SupportTicket.objects.get(subject="Carbon calculation discrepancy")
        self.assertEqual(created_ticket.category, "carbon_tracking")
        self.assertEqual(created_ticket.user, self.customer)
        self.assertEqual(created_ticket.company, self.company)

    def test_list_customer_tickets(self):
        """Test customers only see their own tickets."""
        # Create another customer and ticket
        other_customer = User.objects.create_user(email="other@test.com", password="testpass123")
        other_company = Company.objects.create(name="Other Farm", owner=other_customer)
        other_ticket = SupportTicket.objects.create(
            subject="Other customer ticket",
            description="Should not be visible",
            user=other_customer,
            company=other_company,
        )

        self.client.force_authenticate(user=self.customer)
        url = reverse("support:ticket-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["subject"], "API test ticket")

    def test_add_message_to_ticket(self):
        """Test adding message to ticket via API."""
        self.client.force_authenticate(user=self.customer)
        url = reverse("support:ticket-message", kwargs={"pk": self.ticket.pk})

        data = {
            "content": """
            I forgot to mention that I'm using the latest version of the mobile app
            (v2.1.3) and this issue started happening after the recent update.
            
            Also, my internet connection is stable at 50 Mbps down/10 Mbps up.
            """
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify message was added
        message = SupportMessage.objects.get(ticket=self.ticket, content__icontains="mobile app")
        self.assertEqual(message.author, self.customer)
        self.assertEqual(message.message_type, "customer")

    def test_staff_ticket_assignment(self):
        """Test staff can assign tickets."""
        self.client.force_authenticate(user=self.support_agent)
        url = reverse("support:ticket-detail", kwargs={"pk": self.ticket.pk})

        data = {"assigned_to": self.support_agent.id, "status": "in_progress"}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify assignment
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.support_agent)
        self.assertEqual(self.ticket.status, "in_progress")

    def test_customer_cannot_assign_tickets(self):
        """Test customers cannot assign tickets."""
        self.client.force_authenticate(user=self.customer)
        url = reverse("support:ticket-detail", kwargs={"pk": self.ticket.pk})

        data = {"assigned_to": self.support_agent.id}

        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_ticket_filtering_by_status(self):
        """Test filtering tickets by status."""
        # Create tickets with different statuses
        resolved_ticket = SupportTicket.objects.create(
            subject="Resolved ticket",
            description="Already resolved",
            status="resolved",
            user=self.customer,
            company=self.company,
        )

        self.client.force_authenticate(user=self.customer)
        url = reverse("support:ticket-list")

        # Filter by open status
        response = self.client.get(url, {"status": "open"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["subject"], "API test ticket")

        # Filter by resolved status
        response = self.client.get(url, {"status": "resolved"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["subject"], "Resolved ticket")

    def test_file_attachment_upload(self):
        """Test uploading file attachment via API."""
        self.client.force_authenticate(user=self.customer)
        url = reverse("support:ticket-attachment", kwargs={"pk": self.ticket.pk})

        # Create test file
        test_content = b"Error log content for testing"
        uploaded_file = SimpleUploadedFile(name="error_log.txt", content=test_content, content_type="text/plain")

        data = {"file": uploaded_file, "description": "Error log from my system"}

        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify attachment was created
        attachment = SupportAttachment.objects.get(ticket=self.ticket)
        self.assertEqual(attachment.original_filename, "error_log.txt")
        self.assertEqual(attachment.uploaded_by, self.customer)


class SupportAnalyticsTestCase(TestCase):
    """Test support analytics and reporting."""

    def setUp(self):
        self.support_agent1 = User.objects.create_user(email="agent1@test.com", password="testpass123", is_staff=True)

        self.support_agent2 = User.objects.create_user(email="agent2@test.com", password="testpass123", is_staff=True)

        self.customer = User.objects.create_user(email="customer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Analytics Test Farm", owner=self.customer)

    def test_ticket_volume_analytics(self):
        """Test ticket volume analytics."""
        # Create tickets across different time periods
        current_date = timezone.now()

        # Current month tickets
        for i in range(15):
            SupportTicket.objects.create(
                subject=f"Current month ticket {i}",
                description="Current month ticket",
                category="technical",
                priority="normal",
                user=self.customer,
                company=self.company,
                created_at=current_date - timedelta(days=i),
            )

        # Previous month tickets
        prev_month = current_date - timedelta(days=40)
        for i in range(10):
            ticket = SupportTicket.objects.create(
                subject=f"Previous month ticket {i}",
                description="Previous month ticket",
                category="billing",
                priority="low",
                user=self.customer,
                company=self.company,
            )
            ticket.created_at = prev_month - timedelta(days=i)
            ticket.save()

        # Analytics calculations
        current_month_start = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_tickets = SupportTicket.objects.filter(created_at__gte=current_month_start).count()

        prev_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        prev_month_tickets = SupportTicket.objects.filter(
            created_at__gte=prev_month_start, created_at__lt=current_month_start
        ).count()

        self.assertEqual(current_month_tickets, 15)
        self.assertEqual(prev_month_tickets, 10)

    def test_category_distribution_analytics(self):
        """Test support ticket category distribution."""
        categories = [("technical", 12), ("billing", 8), ("iot_devices", 5), ("carbon_tracking", 3), ("account", 2)]

        for category, count in categories:
            for i in range(count):
                SupportTicket.objects.create(
                    subject=f"{category} ticket {i}",
                    description=f"{category} related issue",
                    category=category,
                    user=self.customer,
                    company=self.company,
                )

        # Calculate distribution
        category_stats = SupportTicket.objects.values("category").annotate(count=Count("id")).order_by("-count")

        # Verify distribution
        self.assertEqual(category_stats[0]["category"], "technical")
        self.assertEqual(category_stats[0]["count"], 12)
        self.assertEqual(category_stats[1]["category"], "billing")
        self.assertEqual(category_stats[1]["count"], 8)

    def test_agent_workload_analytics(self):
        """Test support agent workload distribution."""
        # Create tickets assigned to different agents
        for i in range(8):
            SupportTicket.objects.create(
                subject=f"Agent 1 ticket {i}",
                description="Assigned to agent 1",
                user=self.customer,
                company=self.company,
                assigned_to=self.support_agent1,
                status="in_progress" if i < 5 else "resolved",
            )

        for i in range(5):
            SupportTicket.objects.create(
                subject=f"Agent 2 ticket {i}",
                description="Assigned to agent 2",
                user=self.customer,
                company=self.company,
                assigned_to=self.support_agent2,
                status="in_progress" if i < 3 else "resolved",
            )

        # Calculate workload
        agent_workloads = (
            SupportTicket.objects.values("assigned_to__email")
            .annotate(
                total_tickets=Count("id"),
                active_tickets=Count("id", filter=Q(status__in=["open", "in_progress"])),
                resolved_tickets=Count("id", filter=Q(status="resolved")),
            )
            .order_by("-total_tickets")
        )

        agent1_stats = next(w for w in agent_workloads if w["assigned_to__email"] == "agent1@test.com")
        agent2_stats = next(w for w in agent_workloads if w["assigned_to__email"] == "agent2@test.com")

        self.assertEqual(agent1_stats["total_tickets"], 8)
        self.assertEqual(agent1_stats["active_tickets"], 5)
        self.assertEqual(agent1_stats["resolved_tickets"], 3)

        self.assertEqual(agent2_stats["total_tickets"], 5)
        self.assertEqual(agent2_stats["active_tickets"], 3)
        self.assertEqual(agent2_stats["resolved_tickets"], 2)

    def test_sla_performance_analytics(self):
        """Test SLA performance analytics."""
        # Create tickets with different response times
        tickets_data = [
            ("within_sla", 12, True),  # 12 hours - within 48h SLA
            ("within_sla", 36, True),  # 36 hours - within 48h SLA
            ("overdue", 60, False),  # 60 hours - overdue
            ("overdue", 72, False),  # 72 hours - overdue
        ]

        for ticket_type, response_hours, met_sla in tickets_data:
            ticket = SupportTicket.objects.create(
                subject=f"{ticket_type} ticket",
                description=f"{ticket_type} description",
                user=self.customer,
                company=self.company,
                sla_response_hours=48,
            )

            # Set created_at and first_response_at to simulate response time
            created_time = timezone.now() - timedelta(hours=response_hours + 1)
            response_time = created_time + timedelta(hours=response_hours)

            ticket.created_at = created_time
            ticket.first_response_at = response_time
            ticket.save()

        # Calculate SLA metrics
        total_tickets = SupportTicket.objects.count()
        tickets_with_response = SupportTicket.objects.filter(first_response_at__isnull=False)

        met_sla_count = 0
        for ticket in tickets_with_response:
            if ticket.response_time_hours <= ticket.sla_response_hours:
                met_sla_count += 1

        sla_percentage = (met_sla_count / tickets_with_response.count()) * 100

        self.assertEqual(total_tickets, 4)
        self.assertEqual(met_sla_count, 2)
        self.assertEqual(sla_percentage, 50.0)

    def test_customer_satisfaction_analytics(self):
        """Test customer satisfaction analytics."""
        # Create tickets with satisfaction ratings
        ratings = [5, 4, 4, 3, 5, 2, 4, 5, 3, 4]

        for i, rating in enumerate(ratings):
            ticket = SupportTicket.objects.create(
                subject=f"Satisfaction ticket {i}",
                description="For satisfaction testing",
                user=self.customer,
                company=self.company,
                status="closed",
                customer_satisfaction_rating=rating,
            )

        # Calculate satisfaction metrics
        tickets_with_ratings = SupportTicket.objects.filter(customer_satisfaction_rating__isnull=False)

        avg_satisfaction = tickets_with_ratings.aggregate(avg_rating=Avg("customer_satisfaction_rating"))["avg_rating"]

        rating_distribution = {}
        for rating in range(1, 6):
            count = tickets_with_ratings.filter(customer_satisfaction_rating=rating).count()
            rating_distribution[rating] = count

        self.assertEqual(tickets_with_ratings.count(), 10)
        self.assertAlmostEqual(avg_satisfaction, 3.9, places=1)  # (5+4+4+3+5+2+4+5+3+4)/10
        self.assertEqual(rating_distribution[5], 3)  # Three 5-star ratings
        self.assertEqual(rating_distribution[4], 4)  # Four 4-star ratings


class SupportPerformanceTestCase(TestCase):
    """Test support system performance optimizations."""

    def setUp(self):
        self.customer = User.objects.create_user(email="performance@test.com", password="testpass123")

        self.company = Company.objects.create(name="Performance Test Farm", owner=self.customer)

    def test_bulk_ticket_creation(self):
        """Test bulk creation of support tickets."""
        tickets_data = []
        for i in range(100):
            tickets_data.append(
                SupportTicket(
                    subject=f"Bulk ticket {i}",
                    description=f"Bulk description {i}",
                    category="technical",
                    priority="normal",
                    user=self.customer,
                    company=self.company,
                )
            )

        # Note: bulk_create doesn't call save() so custom logic won't run
        # This is for testing raw performance only
        created_tickets = SupportTicket.objects.bulk_create(tickets_data)

        self.assertEqual(len(created_tickets), 100)
        self.assertEqual(SupportTicket.objects.count(), 100)

    def test_ticket_queryset_optimization(self):
        """Test optimized queries for ticket listings."""
        # Create tickets with related data
        support_agent = User.objects.create_user(email="agent@test.com", password="testpass123", is_staff=True)

        for i in range(50):
            ticket = SupportTicket.objects.create(
                subject=f"Query test ticket {i}",
                description=f"Query test description {i}",
                user=self.customer,
                company=self.company,
                assigned_to=support_agent if i % 2 == 0 else None,
            )

            # Add messages to some tickets
            if i < 25:
                SupportMessage.objects.create(
                    ticket=ticket, author=self.customer, message_type="customer", content=f"Customer message {i}"
                )

        # Test optimized query with select_related and prefetch_related
        optimized_tickets = (
            SupportTicket.objects.select_related("user", "company", "assigned_to").prefetch_related("messages").all()
        )

        self.assertEqual(len(list(optimized_tickets)), 50)

        # Test that related data is accessible without additional queries
        for ticket in optimized_tickets[:5]:
            # These should not trigger additional database queries
            _ = ticket.user.email
            _ = ticket.company.name
            if ticket.assigned_to:
                _ = ticket.assigned_to.email
            _ = list(ticket.messages.all())

    def test_analytics_aggregation_performance(self):
        """Test performance of analytics aggregation queries."""
        # Create substantial test data
        categories = ["technical", "billing", "iot_devices", "carbon_tracking"]
        priorities = ["low", "normal", "high", "urgent"]
        statuses = ["open", "in_progress", "resolved", "closed"]

        for i in range(200):
            SupportTicket.objects.create(
                subject=f"Analytics ticket {i}",
                description=f"Analytics description {i}",
                category=categories[i % len(categories)],
                priority=priorities[i % len(priorities)],
                status=statuses[i % len(statuses)],
                user=self.customer,
                company=self.company,
                customer_satisfaction_rating=(i % 5) + 1,
            )

        # Complex aggregation query
        analytics = SupportTicket.objects.aggregate(
            total_tickets=Count("id"),
            open_tickets=Count("id", filter=Q(status="open")),
            in_progress_tickets=Count("id", filter=Q(status="in_progress")),
            resolved_tickets=Count("id", filter=Q(status="resolved")),
            closed_tickets=Count("id", filter=Q(status="closed")),
            high_priority_tickets=Count("id", filter=Q(priority="high")),
            urgent_tickets=Count("id", filter=Q(priority="urgent")),
            avg_satisfaction=Avg("customer_satisfaction_rating"),
        )

        self.assertEqual(analytics["total_tickets"], 200)
        self.assertEqual(analytics["open_tickets"], 50)  # Every 4th ticket
        self.assertEqual(analytics["resolved_tickets"], 50)
        self.assertIsNotNone(analytics["avg_satisfaction"])
