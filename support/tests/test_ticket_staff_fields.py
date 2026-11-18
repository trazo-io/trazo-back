"""Staff-only ticket fields are written by support staff only, and internal notes are theirs to read.

Overall review 2026-11, OV-SEC-C08. A customer could PATCH their own ticket's `assigned_to` to any
user id, and `assigned_to_name` echoed that user's full name: every account's name, one id at a
time, across companies. They could also read and rewrite the staff's `internal_notes`, and raise
their own priority to "urgent" after creation, which the create serializer refuses.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company
from support.models import SupportTicket
from users.models import User, WorksIn


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Blue Oak Orchards")
        self.customer = User.objects.create_user(
            email="grower@blueoak.example", password="pw-for-test-only", first_name="Sam", last_name="Grower"
        )
        WorksIn.objects.create(user=self.customer, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.stranger = User.objects.create_user(
            email="someone@elsewhere.example", password="pw-for-test-only", first_name="Private", last_name="Person"
        )
        self.staff = User.objects.create_user(
            email="support@trazo.example", password="pw-for-test-only", first_name="Support", is_staff=True
        )
        self.ticket = SupportTicket.objects.create(
            subject="Export question",
            description="The audit export is missing a parcel.",
            user=self.customer,
            company=self.company,
            internal_notes="Customer is on a comped pilot; check with Oscar first.",
        )
        self.url = f"/api/support/tickets/{self.ticket.id}/"

    def _as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


class ACustomerCannotWriteStaffFieldsTests(_Base):
    def test_assigning_a_ticket_to_any_user_id_neither_saves_nor_echoes_their_name(self):
        response = self._as(self.customer).patch(self.url, {"assigned_to": self.stranger.id}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data["assigned_to"])
        self.assertNotIn("Private", str(response.data))
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to_id)

    def test_internal_notes_are_neither_shown_nor_written(self):
        client = self._as(self.customer)
        read = client.get(self.url)
        self.assertEqual(read.status_code, 200)
        self.assertNotIn("internal_notes", read.data)
        self.assertNotIn("comped pilot", str(read.data))
        listed = client.get("/api/support/tickets/")
        self.assertNotIn("comped pilot", str(listed.data))

        client.patch(self.url, {"internal_notes": "rewritten"}, format="json")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.internal_notes, "Customer is on a comped pilot; check with Oscar first.")

    def test_priority_status_and_tags_stay_as_staff_set_them(self):
        # Valid values, so a 200 that changes nothing is the serializer refusing them, not a 400.
        response = self._as(self.customer).patch(
            self.url, {"priority": "urgent", "status": "resolved", "tags": "vip"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, "normal")
        self.assertEqual(self.ticket.status, "open")
        self.assertEqual(self.ticket.tags, "")

    def test_the_customer_still_edits_their_own_words(self):
        response = self._as(self.customer).patch(
            self.url, {"subject": "Export missing Block 4", "category": "technical"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.subject, "Export missing Block 4")
        self.assertEqual(self.ticket.category, "technical")


class StaffKeepTheirFieldsTests(_Base):
    def test_staff_read_and_write_internal_notes_and_priority(self):
        client = self._as(self.staff)
        read = client.get(self.url)
        self.assertEqual(read.data["internal_notes"], "Customer is on a comped pilot; check with Oscar first.")
        response = client.patch(self.url, {"internal_notes": "Answered.", "priority": "high"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.internal_notes, "Answered.")
        self.assertEqual(self.ticket.priority, "high")


class AnOutsiderCannotReachAnotherCompanysTicketTests(_Base):
    def test_a_member_of_another_company_gets_404(self):
        other = Company.objects.create(name="Other Farm")
        outsider = User.objects.create_user(email="admin@other.example", password="pw-for-test-only")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        client = self._as(outsider)
        self.assertEqual(client.get(self.url).status_code, 404)
        self.assertEqual(client.patch(self.url, {"subject": "x"}, format="json").status_code, 404)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.subject, "Export question")
