"""Accepting an invitation never leaves a company with farms and no Company Admin (OV-SEC-C11).

Accepting moves the invitee out of every other company. The review reproduced it on 2026-11-10: the
sole Company Admin of company 8 accepted a Viewer invitation to company 7, and company 8 kept its data
with 0 members. The accept screen warned about a transfer, in English only, and never said that.

Pinned here:
  * the accept endpoint refuses a sole Company Admin of a company with a farm (409, a code and the
    companies), and changes nothing;
  * another admin in that company, an empty company, or a non-admin membership does not block;
  * `accept()` refuses the same case for the sign-up and sign-in paths, which leave it pending;
  * the details endpoint tells the signed-in invitee what accepting leaves, and tells no one else.
"""

from django.core.cache import caches
from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from company.models import Company, Establishment
from users.models import User, WorksIn
from users.models_invitation import CompanyInvitation, SoleAdminTransferError


class _Invite(TestCase):
    def setUp(self):
        for alias in ("default", "throttle"):
            try:
                caches[alias].clear()
            except Exception:  # noqa: BLE001 - a cache alias the test settings do not define
                pass
        self.inviter = User.objects.create_user(email="advisor@test.com", password="x", is_verified=True)
        self.target = Company.objects.create(name="Advisor Co")
        WorksIn.objects.create(user=self.inviter, company=self.target, role=WorksIn.COMPANY_ADMIN)

        self.grower = User.objects.create_user(email="grower@test.com", password="x", is_verified=True)
        self.home = Company.objects.create(name="Home Orchard")
        Establishment.objects.create(name="Home Block", company=self.home)
        self.membership = WorksIn.objects.create(user=self.grower, company=self.home, role=WorksIn.COMPANY_ADMIN)

        self.invitation = CompanyInvitation.objects.create(
            email="grower@test.com", company=self.target, role=WorksIn.VIEWER, inviter=self.inviter
        )
        self.client = APIClient()

    def _accept(self, user=None):
        self.client.force_authenticate(user or self.grower)
        return self.client.post(
            reverse("accept_invitation", kwargs={"invitation_code": self.invitation.invitation_code})
        )

    def _details(self, user=None):
        if user is not None:
            self.client.force_authenticate(user)
        return self.client.get(
            reverse("get_invitation_details", kwargs={"invitation_code": self.invitation.invitation_code})
        ).json()


class RefusalTests(_Invite):
    def test_a_sole_admin_of_a_company_with_a_farm_is_refused_and_nothing_changes(self):
        response = self._accept()
        self.assertEqual(response.status_code, 409, response.content)
        body = response.json()
        self.assertEqual(body["code"], "sole_company_admin")
        self.assertEqual(body["companies"], ["Home Orchard"])
        self.assertIn("only Company Admin of Home Orchard", body["error"])
        self.assertTrue(WorksIn.objects.filter(pk=self.membership.pk).exists())
        self.assertFalse(WorksIn.objects.filter(user=self.grower, company=self.target).exists())
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, CompanyInvitation.STATUS_PENDING)

    def test_the_model_refuses_it_for_the_sign_up_and_sign_in_paths(self):
        with self.assertRaises(SoleAdminTransferError) as raised:
            self.invitation.accept(self.grower)
        self.assertEqual(raised.exception.companies, ["Home Orchard"])
        self.assertTrue(WorksIn.objects.filter(pk=self.membership.pk).exists())

    def test_the_sign_in_path_leaves_the_invitation_pending(self):
        from users.views_invitation import process_pending_invitation

        self.assertIsNone(process_pending_invitation(self.grower, self.invitation.invitation_code))
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, CompanyInvitation.STATUS_PENDING)
        self.assertTrue(WorksIn.objects.filter(pk=self.membership.pk).exists())


class SetupOperatorTests(_Invite):
    def test_the_pilot_setup_operator_is_not_another_admin(self):
        """Review of back #481: a pilot company has the grower and Trazo's setup operator as Company Admins;
        `users/team.py` does not count the operator as a remaining admin, and neither does this."""
        operator = User.objects.create_user(email="setup@trazo.test", password="x")
        WorksIn.objects.create(user=operator, company=self.home, role=WorksIn.COMPANY_ADMIN, is_setup_operator=True)
        response = self._accept()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertTrue(WorksIn.objects.filter(pk=self.membership.pk).exists())


class WhatDoesNotBlockTests(_Invite):
    def test_another_admin_in_the_old_company(self):
        partner = User.objects.create_user(email="partner@test.com", password="x")
        WorksIn.objects.create(user=partner, company=self.home, role=WorksIn.COMPANY_ADMIN)
        self.assertEqual(self._accept().status_code, 200)
        self.assertFalse(WorksIn.objects.filter(user=self.grower, company=self.home).exists())
        self.assertTrue(WorksIn.objects.filter(user=self.grower, company=self.target).exists())

    def test_an_old_company_with_no_farm(self):
        Establishment.objects.filter(company=self.home).delete()
        self.assertEqual(self._accept().status_code, 200)

    def test_a_membership_that_is_not_admin(self):
        self.membership.role = WorksIn.VIEWER
        self.membership.save()
        owner = User.objects.create_user(email="owner@test.com", password="x")
        WorksIn.objects.create(user=owner, company=self.home, role=WorksIn.COMPANY_ADMIN)
        self.assertEqual(self._accept().status_code, 200)


class DetailsTests(_Invite):
    def test_the_signed_in_invitee_is_told_what_accepting_leaves(self):
        body = self._details(self.grower)
        self.assertEqual(body["transfer"], {"leaves": ["Home Orchard"], "sole_admin_of": ["Home Orchard"]})

    def test_no_one_else_is_told_anything_about_the_account(self):
        self.assertNotIn("transfer", self._details())
        stranger = User.objects.create_user(email="stranger@test.com", password="x")
        self.assertNotIn("transfer", self._details(stranger))
