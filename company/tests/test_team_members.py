"""Settings > Team: a Company Admin removes a member or changes their role.

`PATCH|DELETE /api/companies/<id>/members/<membership_id>/`. Until 2026-11-10 nothing but the
`remove_pilot_operator` command deleted a WorksIn row, while the Team tab told admins that members
"keep their access until they are removed from the team". The rules live in `users/team.py`.
"""

from django.conf import settings
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from company.models import Company, Establishment
from product.models import Parcel
from users import team
from users.constants import PRODUCER
from users.models import User, WorksIn


def _user(email):
    return User.objects.create_user(
        email=email,
        password="x",
        first_name=email.split("@")[0].title(),
        last_name="Test",
        user_type=PRODUCER,
        is_active=True,
    )


def _member(company, email, role, **extra):
    user = _user(email)
    return WorksIn.objects.create(user=user, company=company, role=role, **extra)


class TeamFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Loma Orchards")
        cls.farm_a = Establishment.objects.create(name="North Block", company=cls.company)
        cls.farm_b = Establishment.objects.create(name="South Block", company=cls.company)
        cls.parcel = Parcel.objects.create(name="Row 4", establishment=cls.farm_a, area=2.0)
        cls.admin = _member(cls.company, "ana@loma.example", WorksIn.COMPANY_ADMIN)
        cls.manager = _member(cls.company, "beto@loma.example", WorksIn.FARM_MANAGER)
        cls.manager.establishments_in_charge.set([cls.farm_a])
        cls.viewer = _member(cls.company, "cruz@loma.example", WorksIn.VIEWER)

    def setUp(self):
        self.client = APIClient()

    def _as(self, membership):
        self.client.force_authenticate(membership.user)
        return self.client

    def _url(self, membership, company=None):
        return f"/api/companies/{(company or self.company).pk}/members/{membership.pk}/"


class MembersListTests(TeamFixture):
    def test_rows_carry_a_membership_id_and_keep_id_as_the_company(self):
        response = self._as(self.admin).get(f"/api/companies/{self.company.pk}/members/")
        self.assertEqual(response.status_code, 200)
        rows = {row["membership_id"]: row for row in response.json()}
        self.assertEqual(set(rows), {self.admin.pk, self.manager.pk, self.viewer.pk})
        for row in rows.values():
            # `id` is the company in the shared WorksInSerializer (the user payload reads it so).
            self.assertEqual(row["id"], self.company.pk)
        self.assertEqual(rows[self.manager.pk]["role_code"], WorksIn.FARM_MANAGER)
        self.assertEqual(rows[self.manager.pk]["role"], "Farm Manager")

    def test_admin_may_manage_everyone_but_themself(self):
        rows = {
            r["membership_id"]: r for r in self._as(self.admin).get(f"/api/companies/{self.company.pk}/members/").json()
        }
        self.assertEqual(
            {pk: (r["can_manage"], r["is_you"]) for pk, r in rows.items()},
            {self.admin.pk: (False, True), self.manager.pk: (True, False), self.viewer.pk: (True, False)},
        )

    def test_non_admins_are_offered_no_controls(self):
        for caller in (self.manager, self.viewer):
            with self.subTest(role=caller.role):
                rows = self._as(caller).get(f"/api/companies/{self.company.pk}/members/").json()
                self.assertEqual(len(rows), 3)
                self.assertFalse(any(r["can_manage"] for r in rows))

    def test_user_payload_companies_are_unchanged(self):
        """`UserSerializer.companies` shares WorksInSerializer; the new fields stay off it."""
        from users.serializers import WorksInSerializer

        data = WorksInSerializer(self.admin).data
        self.assertEqual(data["id"], self.company.pk)
        self.assertNotIn("membership_id", data)
        self.assertNotIn("can_manage", data)


class RemoveMemberTests(TeamFixture):
    def test_admin_removes_a_member(self):
        response = self._as(self.admin).delete(self._url(self.manager))
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(WorksIn.objects.filter(pk=self.manager.pk).exists())
        # The membership goes, the account and the company's farms stay.
        self.assertTrue(User.objects.filter(pk=self.manager.user_id).exists())
        self.assertEqual(self.company.establishment_set.count(), 2)

    def test_admin_cannot_remove_themself(self):
        response = self._as(self.admin).delete(self._url(self.admin))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], team.SELF)
        self.assertTrue(WorksIn.objects.filter(pk=self.admin.pk).exists())

    def test_another_admin_can_remove_an_admin(self):
        second = _member(self.company, "dora@loma.example", WorksIn.COMPANY_ADMIN)
        self.assertEqual(self._as(second).delete(self._url(self.admin)).status_code, 204)
        self.assertFalse(WorksIn.objects.filter(pk=self.admin.pk).exists())

    def test_farm_manager_and_viewer_cannot_remove_anyone(self):
        for caller in (self.manager, self.viewer):
            with self.subTest(role=caller.role):
                response = self._as(caller).delete(self._url(self.viewer if caller is self.manager else self.manager))
                self.assertEqual(response.status_code, 403)
        self.assertEqual(WorksIn.objects.filter(company=self.company).count(), 3)


class ChangeRoleTests(TeamFixture):
    def test_admin_promotes_a_viewer(self):
        response = self._as(self.admin).patch(self._url(self.viewer), {"role": WorksIn.FARM_MANAGER}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["role_code"], WorksIn.FARM_MANAGER)
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.role, WorksIn.FARM_MANAGER)

    def test_demoted_admin_keeps_every_farm_they_could_reach(self):
        second = _member(self.company, "dora@loma.example", WorksIn.COMPANY_ADMIN)
        self.assertEqual(second.establishments_in_charge.count(), 0)
        response = self._as(self.admin).patch(self._url(second), {"role": WorksIn.VIEWER}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        second.refresh_from_db()
        self.assertEqual(second.role, WorksIn.VIEWER)
        self.assertEqual(set(second.establishments_in_charge.all()), {self.farm_a, self.farm_b})

    def test_farm_list_untouched_when_the_role_does_not_leave_admin(self):
        self._as(self.admin).patch(self._url(self.manager), {"role": WorksIn.VIEWER}, format="json")
        self.assertEqual(list(self.manager.establishments_in_charge.all()), [self.farm_a])

    def test_admin_cannot_change_their_own_role(self):
        response = self._as(self.admin).patch(self._url(self.admin), {"role": WorksIn.VIEWER}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], team.SELF)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, WorksIn.COMPANY_ADMIN)

    def test_unknown_role_is_refused(self):
        response = self._as(self.admin).patch(self._url(self.viewer), {"role": "SUPER"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.json())
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.role, WorksIn.VIEWER)

    def test_viewer_cannot_promote_themself(self):
        response = self._as(self.viewer).patch(self._url(self.viewer), {"role": WorksIn.COMPANY_ADMIN}, format="json")
        self.assertEqual(response.status_code, 403)
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.role, WorksIn.VIEWER)


class SetupOperatorTests(TeamFixture):
    """The pilot operator's row is Trazo's to remove (`remove_pilot_operator`), and the operator
    does not decide who is on the grower's team."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.operator = _member(cls.company, "oscar+loma@trazo.io", WorksIn.COMPANY_ADMIN, is_setup_operator=True)

    def test_grower_admin_cannot_remove_or_demote_the_setup_operator(self):
        client = self._as(self.admin)
        self.assertEqual(client.delete(self._url(self.operator)).json()["code"], team.SETUP_OPERATOR_TARGET)
        response = client.patch(self._url(self.operator), {"role": WorksIn.VIEWER}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], team.SETUP_OPERATOR_TARGET)
        self.operator.refresh_from_db()
        self.assertEqual(self.operator.role, WorksIn.COMPANY_ADMIN)

    def test_setup_operator_cannot_change_the_team(self):
        client = self._as(self.operator)
        response = client.delete(self._url(self.manager))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], team.SETUP_OPERATOR_CALLER)
        response = client.patch(self._url(self.admin), {"role": WorksIn.VIEWER}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(WorksIn.objects.filter(pk=self.manager.pk).exists())
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, WorksIn.COMPANY_ADMIN)

    def test_list_offers_no_controls_on_or_to_the_setup_operator(self):
        rows = {
            r["membership_id"]: r for r in self._as(self.admin).get(f"/api/companies/{self.company.pk}/members/").json()
        }
        self.assertTrue(rows[self.operator.pk]["is_setup_operator"])
        self.assertFalse(rows[self.operator.pk]["can_manage"])
        operator_view = self._as(self.operator).get(f"/api/companies/{self.company.pk}/members/").json()
        self.assertFalse(any(r["can_manage"] for r in operator_view))


class LastAdminTests(TeamFixture):
    """Over HTTP the self rule already leaves the caller as the remaining admin, so `LAST_ADMIN`
    cannot come back from the endpoint (see users/team.py). The rule is checked directly here, so it
    still holds if the self rule is ever relaxed; the HTTP race is the last test."""

    def test_removing_or_demoting_the_only_admin_is_refused(self):
        caller = WorksIn(pk=999, company=self.company, role=WorksIn.COMPANY_ADMIN)  # not in `rows`
        rows = list(WorksIn.objects.filter(company=self.company))  # caller's own row already gone
        self.assertEqual(team.change_refusal(caller, self.admin, None, rows), team.LAST_ADMIN)
        self.assertEqual(team.change_refusal(caller, self.admin, WorksIn.VIEWER, rows), team.LAST_ADMIN)
        self.assertIsNone(team.change_refusal(caller, self.admin, WorksIn.COMPANY_ADMIN, rows))
        self.assertIsNone(team.change_refusal(caller, self.manager, None, rows))

    def test_a_setup_operator_does_not_count_as_the_remaining_admin(self):
        operator = _member(self.company, "oscar+loma@trazo.io", WorksIn.COMPANY_ADMIN, is_setup_operator=True)
        caller = WorksIn(pk=999, company=self.company, role=WorksIn.COMPANY_ADMIN)
        rows = list(WorksIn.objects.filter(company=self.company))
        self.assertIn(operator, rows)
        self.assertEqual(team.change_refusal(caller, self.admin, None, rows), team.LAST_ADMIN)

    def test_admins_who_removed_each_other_leave_one(self):
        """Sequentially, the second of two admins removing each other is no longer an admin."""
        second = _member(self.company, "dora@loma.example", WorksIn.COMPANY_ADMIN)
        self.assertEqual(self._as(self.admin).delete(self._url(second)).status_code, 204)
        response = self._as(second).delete(self._url(self.admin))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorksIn.objects.filter(company=self.company, role=WorksIn.COMPANY_ADMIN).count(), 1)


class MemberTenancyTests(TeamFixture):
    """Another company's membership id must answer exactly like an id that does not exist."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_co = Company.objects.create(name="Victim Farms")
        cls.other_admin = _member(cls.other_co, "admin@victim.example", WorksIn.COMPANY_ADMIN)
        cls.other_member = _member(cls.other_co, "crew@victim.example", WorksIn.FARM_MANAGER)

    def _missing_url(self):
        missing = WorksIn.objects.order_by("-pk").first().pk + 1000
        return f"/api/companies/{self.company.pk}/members/{missing}/"

    def test_another_companys_membership_under_own_url_is_a_plain_404(self):
        client = self._as(self.admin)
        cases = {
            "delete": lambda url: client.delete(url),
            "patch": lambda url: client.patch(url, {"role": WorksIn.VIEWER}, format="json"),
            # An invalid body must not be read before the lookup: that would answer 400 for a real
            # foreign row and 404 for a missing one.
            "patch_invalid": lambda url: client.patch(url, {"role": "SUPER"}, format="json"),
        }
        for name, call in cases.items():
            with self.subTest(case=name):
                foreign = call(self._url(self.other_member))
                missing = call(self._missing_url())
                self.assertEqual(foreign.status_code, 404)
                self.assertEqual((foreign.status_code, foreign.content), (missing.status_code, missing.content))
        self.other_member.refresh_from_db()
        self.assertEqual(self.other_member.role, WorksIn.FARM_MANAGER)

    def test_outsider_admin_cannot_change_another_companys_team(self):
        client = self._as(self.admin)
        url = self._url(self.other_member, company=self.other_co)
        self.assertEqual(client.delete(url).status_code, 403)
        self.assertEqual(client.patch(url, {"role": WorksIn.VIEWER}, format="json").status_code, 403)
        # Same answer for a membership that does not exist there.
        missing = f"/api/companies/{self.other_co.pk}/members/{self.other_member.pk + 1000}/"
        self.assertEqual(client.delete(url).content, client.delete(missing).content)
        self.other_member.refresh_from_db()
        self.assertEqual(self.other_member.role, WorksIn.FARM_MANAGER)

    def test_own_admin_still_acts_on_own_team(self):
        """The control: the same request on the caller's own member succeeds."""
        response = self._as(self.other_admin).patch(
            self._url(self.other_member, company=self.other_co), {"role": WorksIn.VIEWER}, format="json"
        )
        self.assertEqual(response.status_code, 200)


class RemovalRevokesAccessTests(TeamFixture):
    """The JWT names the account, never its memberships, so the removed member's very next request,
    on the cookie they already hold, is refused."""

    def _cookie_client(self, membership):
        client = APIClient()
        client.cookies[settings.SIMPLE_JWT.get("AUTH_COOKIE", "access_token")] = str(
            RefreshToken.for_user(membership.user).access_token
        )
        return client

    def test_removed_member_is_refused_on_the_next_request(self):
        member = self._cookie_client(self.manager)
        company_url = f"/api/companies/{self.company.pk}/"
        farm_url = f"/api/companies/{self.company.pk}/establishments/{self.farm_a.pk}/"
        members_url = f"/api/companies/{self.company.pk}/members/"

        # Before: the same cookie reads the company, its farm and its parcel.
        self.assertEqual(member.get(company_url).status_code, 200)
        self.assertEqual(member.get(farm_url).status_code, 200)
        self.assertEqual(member.get(members_url).status_code, 200)
        self.assertIn(self.parcel.pk, [p["id"] for p in _rows(member.get("/api/parcels/"))])

        self.assertEqual(self._as(self.admin).delete(self._url(self.manager)).status_code, 204)

        self.assertIn(member.get(company_url).status_code, (403, 404))
        self.assertIn(member.get(farm_url).status_code, (403, 404))
        self.assertIn(member.get(members_url).status_code, (403, 404))
        self.assertEqual(member.get(f"/api/parcels/{self.parcel.pk}/").status_code, 404)
        self.assertNotIn(self.parcel.pk, [p["id"] for p in _rows(member.get("/api/parcels/"))])


def _rows(response):
    data = response.json()
    return data.get("results", data) if isinstance(data, dict) else data
