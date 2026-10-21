"""A write cannot point a row at another company's records.

A `PrimaryKeyRelatedField` checks the id against its queryset, and the default queryset is every row
of the model, so six serializers accepted another tenant's id in the request body. Found by the
2026-10-20 route inventory (`backend/route_tenancy.py`); reproduced here before the fix:

  * parcel `establishment`: PATCH moved a parcel, with its seasons, onto another company's farm
  * crop history `parcel`: false 205.202 land history planted on another company's parcel, which
    prints in its audit export and OSP
  * carbon entry `establishment_id`: emissions planted in another company's carbon figures
  * OSP `certification`: another company's certificate linked into your plan
  * landowner affidavit `osp`: an affidavit attached to another company's OSP
  * support attachment `ticket`: a file dropped into another company's support ticket

The fix is `backend.permissions.CallerScopedRelatedFields`: each field's queryset is narrowed to the
caller's companies, so a foreign id fails with DRF's own "does not exist" error.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework.test import APIClient

from carbon.models import CarbonEntry
from certifications.models import Certification, LandownerAffidavit, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelCropHistory
from support.models import SupportAttachment, SupportTicket
from users.constants import PRODUCER
from users.models import User, WorksIn


def _admin_of(company, email):
    user = User.objects.create_user(
        email=email, password="x", first_name="T", last_name="T", user_type=PRODUCER, is_active=True
    )
    WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
    return user


class _Tenants(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.victim_co = Company.objects.create(name="Victim Farms")
        cls.victim = _admin_of(cls.victim_co, "admin@victim.example")
        cls.victim_farm = Establishment.objects.create(name="Victim Farm", company=cls.victim_co)
        cls.victim_parcel = Parcel.objects.create(name="Victim Parcel", establishment=cls.victim_farm, area=2.0)
        cls.victim_season = History.objects.create(name="Victim 2026", parcel=cls.victim_parcel)
        cls.victim_cert = Certification.objects.create(establishment=cls.victim_farm, certification_type="usda_organic")
        cls.victim_osp = OrganicSystemPlan.objects.create(establishment=cls.victim_farm, version_number=1)
        cls.victim_ticket = SupportTicket.objects.create(
            subject="Victim ticket", description="d", user=cls.victim, company=cls.victim_co
        )

        cls.own_co = Company.objects.create(name="Outsider Co")
        cls.me = _admin_of(cls.own_co, "admin@outsider.example")
        cls.own_farm = Establishment.objects.create(name="Own Farm", company=cls.own_co)
        cls.own_farm_2 = Establishment.objects.create(name="Own Farm 2", company=cls.own_co)
        cls.own_parcel = Parcel.objects.create(name="Own Parcel", establishment=cls.own_farm, area=1.0)
        cls.own_cert = Certification.objects.create(establishment=cls.own_farm, certification_type="usda_organic")
        cls.own_osp = OrganicSystemPlan.objects.create(establishment=cls.own_farm, version_number=1)
        cls.own_ticket = SupportTicket.objects.create(subject="Own", description="d", user=cls.me, company=cls.own_co)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def _nested(self, path):
        return f"/api/companies/{self.own_co.id}/establishments/{self.own_farm.id}/{path}"


class ForeignKeyWritesScopedTests(_Tenants):
    def test_parcel_cannot_move_to_another_companys_farm(self):
        url = f"/api/parcels/{self.own_parcel.id}/"
        response = self.client.patch(url, {"establishment": self.victim_farm.id}, format="multipart")
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.own_parcel.refresh_from_db()
        self.assertEqual(self.own_parcel.establishment_id, self.own_farm.id)

    def test_parcel_can_move_between_own_farms(self):
        url = f"/api/parcels/{self.own_parcel.id}/"
        response = self.client.patch(url, {"establishment": self.own_farm_2.id}, format="multipart")
        self.assertEqual(response.status_code, 200, response.content[:300])

    def test_crop_history_cannot_be_written_on_another_companys_parcel(self):
        body = {"parcel": self.victim_parcel.id, "year": 2024, "crop_grown": "PLANTED"}
        response = self.client.post("/api/parcel-crop-history/", body, format="json")
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(ParcelCropHistory.objects.filter(parcel=self.victim_parcel).exists())
        own = self.client.post(
            "/api/parcel-crop-history/", {**body, "parcel": self.own_parcel.id, "crop_grown": "Walnuts"}, format="json"
        )
        self.assertEqual(own.status_code, 201, own.content[:300])

    def test_carbon_entry_cannot_be_planted_on_another_companys_farm(self):
        for field, value in (
            ("establishment_id", self.victim_farm.id),
            ("establishment", self.victim_farm.id),
            ("production_id", self.victim_season.id),
            ("production", self.victim_season.id),
        ):
            with self.subTest(field=field):
                body = {"type": "emission", "amount": 9999, "year": 2026, field: value}
                response = self.client.post("/api/carbon/entries/", body, format="json")
                self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(CarbonEntry.objects.filter(establishment=self.victim_farm).exists())
        self.assertFalse(CarbonEntry.objects.filter(production=self.victim_season).exists())

    def test_osp_cannot_link_another_companys_certification(self):
        url = self._nested(f"osps/{self.own_osp.id}/")
        response = self.client.patch(url, {"certification": self.victim_cert.id}, format="json")
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.own_osp.refresh_from_db()
        self.assertIsNone(self.own_osp.certification_id)
        own = self.client.patch(url, {"certification": self.own_cert.id}, format="json")
        self.assertEqual(own.status_code, 200, own.content[:300])

    def test_affidavit_cannot_attach_to_another_companys_osp(self):
        body = {"parcel": self.own_parcel.id, "previous_manager_name": "Prev", "osp": self.victim_osp.id}
        response = self.client.post(self._nested("affidavits/"), body, format="json")
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(LandownerAffidavit.objects.filter(osp=self.victim_osp).exists())
        own = self.client.post(self._nested("affidavits/"), {**body, "osp": self.own_osp.id}, format="json")
        self.assertEqual(own.status_code, 201, own.content[:300])

    def test_support_attachment_cannot_land_in_another_companys_ticket(self):
        def upload(ticket):
            f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
            return self.client.post("/api/support/attachments/", {"ticket": ticket.id, "file": f}, format="multipart")

        response = upload(self.victim_ticket)
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertFalse(SupportAttachment.objects.filter(ticket=self.victim_ticket).exists())
        self.assertEqual(upload(self.own_ticket).status_code, 201)

    def test_refusal_does_not_confirm_the_id_exists(self):
        """A foreign id and a missing id get the same answer."""
        url = f"/api/parcels/{self.own_parcel.id}/"
        foreign = self.client.patch(url, {"establishment": self.victim_farm.id}, format="multipart")
        missing = self.client.patch(url, {"establishment": 999999}, format="multipart")
        self.assertEqual(foreign.status_code, missing.status_code)
        self.assertEqual(
            str(foreign.data["establishment"][0]).replace(str(self.victim_farm.id), "N"),
            str(missing.data["establishment"][0]).replace("999999", "N"),
        )


class CarbonReadsScopedTests(_Tenants):
    """`by_entity` and `summary` filtered CarbonEntry.objects directly, so any account read any
    farm's entries and totals by naming its id. They now go through the scoped get_queryset."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        CarbonEntry.objects.create(
            establishment=cls.victim_farm, type="emission", amount=123.0, co2e_amount=123.0, year=2026
        )

    def test_by_entity_returns_nothing_for_another_companys_farm(self):
        response = self.client.get(
            "/api/carbon/entries/by_entity/", {"entity_type": "establishment", "entity_id": self.victim_farm.id}
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertNotIn(b"123", response.content)

    def test_summary_returns_nothing_for_another_companys_farm(self):
        response = self.client.get("/api/carbon/entries/summary/", {"establishment": self.victim_farm.id, "year": 2026})
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.data["total_emissions"], 0, response.content[:300])

    def test_owner_still_reads_own_entries(self):
        self.client.force_authenticate(self.victim)
        response = self.client.get(
            "/api/carbon/entries/by_entity/", {"entity_type": "establishment", "entity_id": self.victim_farm.id}
        )
        self.assertIn(b"123", response.content)


class ReviewFollowUpTests(_Tenants):
    """Review findings on #203."""

    def test_parcel_cannot_point_at_another_companys_season(self):
        url = f"/api/parcels/{self.own_parcel.id}/"
        self.client.patch(url, {"current_history": self.victim_season.id}, format="multipart")
        self.own_parcel.refresh_from_db()
        self.assertNotEqual(self.own_parcel.current_history_id, self.victim_season.id)

    def test_osp_cannot_link_another_farms_certificate_in_the_same_company(self):
        other_farm_cert = Certification.objects.create(establishment=self.own_farm_2, certification_type="usda_organic")
        url = self._nested(f"osps/{self.own_osp.id}/")
        response = self.client.patch(url, {"certification": other_farm_cert.id}, format="json")
        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_affidavit_cannot_attach_to_another_farms_osp_in_the_same_company(self):
        other_farm_osp = OrganicSystemPlan.objects.create(establishment=self.own_farm_2, version_number=1)
        body = {"parcel": self.own_parcel.id, "previous_manager_name": "Prev", "osp": other_farm_osp.id}
        response = self.client.post(self._nested("affidavits/"), body, format="json")
        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_support_staff_still_attach_to_any_companys_ticket(self):
        staff = User.objects.create_user(
            email="agent@trazo.example", password="x", first_name="A", last_name="G", user_type=PRODUCER, is_staff=True
        )
        self.client.force_authenticate(staff)
        f = SimpleUploadedFile("reply.txt", b"hi", content_type="text/plain")
        response = self.client.post(
            "/api/support/attachments/", {"ticket": self.victim_ticket.id, "file": f}, format="multipart"
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
