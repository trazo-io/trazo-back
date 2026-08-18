"""
Off-farm post-harvest handler API — CCOF G6.1 / 7 CFR 205.272.

🔴 Why this file exists (2026-08-16, CCOF grower-checklist audit).

`PostHarvestFacility`, `PostHarvestFacilitySerializer` and the audit export's
`_facility_cert_block` all shipped months apart and were never joined: the serializer was
referenced nowhere, no router registered the viewset, and `History.post_harvest_facility`
appeared in no serializer. So the ONE record CCOF's grower checklist asks for when a crop is
sent to another certified operation — the handler's current organic certificate — was
reachable only from Django admin, and the packet's G6.1 block could not render for any real
operation. It printed the ask ("that facility must be a certified organic handler…") on every
packet instead.

These tests pin the three joints that were missing, so the next refactor cannot quietly undo
them again:

  1. the route exists and is company-scoped (a non-member gets nothing),
  2. a production can be linked to a handler through the API, and only to one belonging to
     its OWN farm — otherwise another operation's certificate would print in this packet,
  3. once linked, the audit export actually renders the certificate block.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import PostHarvestFacility
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User, WorksIn


def _text(elements):
    return " ".join(getattr(el, "text", "") or "" for el in elements)


class PostHarvestFacilityRouteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Handler Co")
        self.user = User.objects.create_user(email="phf@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Blue Oak", company=self.company)

        self.other_company = Company.objects.create(name="Other Co")
        self.other_establishment = Establishment.objects.create(name="Other Farm", company=self.other_company)

    def _url(self, establishment=None, company=None):
        company = company or self.company
        establishment = establishment or self.establishment
        return f"/api/companies/{company.id}/establishments/{establishment.id}/post-harvest-facilities/"

    def test_create_and_list(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "name": "Central Valley Hulling",
                "facility_type": "huller",
                "city": "Modesto",
                "state": "CA",
                "certification_number": "CCOF-12345",
                "certifier_name": "CCOF Certification Services",
                "effective_date": (timezone.now().date() - timedelta(days=30)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["name"], "Central Valley Hulling")
        self.assertEqual(resp.data["facility_type_display"], "Huller / Sheller")
        # Certificate issued 30 days ago is inside the ~15-month G6.1 freshness window.
        self.assertIs(resp.data["cert_is_current"], True)

        listing = self.client.get(self._url())
        self.assertEqual(listing.status_code, 200)
        rows = listing.data["results"] if isinstance(listing.data, dict) else listing.data
        self.assertIn("Central Valley Hulling", [row["name"] for row in rows])

    def test_establishment_comes_from_the_url_not_the_body(self):
        """A body-supplied establishment must not move the facility to another farm."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.post(
            self._url(),
            {
                "name": "Body Injection Huller",
                "facility_type": "huller",
                "establishment": self.other_establishment.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        facility = PostHarvestFacility.objects.get(name="Body Injection Huller")
        self.assertEqual(facility.establishment_id, self.establishment.id)

    def test_non_member_cannot_list_another_companys_facilities(self):
        PostHarvestFacility.objects.create(establishment=self.other_establishment, name="Rival Huller")
        self.client.force_authenticate(user=self.user)  # member of self.company only
        resp = self.client.get(self._url(establishment=self.other_establishment, company=self.other_company))
        self.assertIn(resp.status_code, (403, 404), f"cross-company read not denied: {resp.status_code}")

    def test_viewer_cannot_create(self):
        viewer = User.objects.create_user(email="phf-viewer@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(user=viewer)
        resp = self.client.post(self._url(), {"name": "Nope", "facility_type": "packer"}, format="json")
        self.assertEqual(resp.status_code, 403, "read-only viewer was allowed to write")


class ProductionHandlerLinkTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Link Co")
        self.user = User.objects.create_user(email="link@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Link Farm", company=self.company)
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.establishment, area=12.0)
        self.product = Product.objects.create(name="Walnut")
        self.production = History.objects.create(
            name="Walnut 2026",
            parcel=self.parcel,
            product=self.product,
            start_date=timezone.now(),
        )
        self.facility = PostHarvestFacility.objects.create(
            establishment=self.establishment,
            name="Central Valley Hulling",
            facility_type="huller",
            certification_number="CCOF-12345",
            certifier_name="CCOF Certification Services",
            effective_date=timezone.now().date() - timedelta(days=30),
        )
        # A handler registered by a DIFFERENT operation.
        self.foreign_facility = PostHarvestFacility.objects.create(
            establishment=Establishment.objects.create(
                name="Foreign Farm", company=Company.objects.create(name="Foreign Co")
            ),
            name="Foreign Huller",
            facility_type="huller",
        )

    def _url(self):
        return f"/api/histories/{self.production.id}/"

    def test_production_can_be_linked_to_its_own_farms_handler(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(self._url(), {"post_harvest_facility": self.facility.id}, format="json")
        self.assertIn(resp.status_code, (200, 202), resp.content)
        self.production.refresh_from_db()
        self.assertEqual(self.production.post_harvest_facility_id, self.facility.id)

    def test_production_cannot_be_linked_to_another_farms_handler(self):
        """Otherwise a stranger's organic certificate prints inside this operation's packet."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(self._url(), {"post_harvest_facility": self.foreign_facility.id}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.production.refresh_from_db()
        self.assertIsNone(self.production.post_harvest_facility_id)

    def test_detail_payload_carries_the_certificate_summary(self):
        self.production.post_harvest_facility = self.facility
        self.production.save(update_fields=["post_harvest_facility"])
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        detail = resp.data.get("post_harvest_facility_detail")
        self.assertIsNotNone(detail, "handler summary missing from the production payload")
        self.assertEqual(detail["name"], "Central Valley Hulling")
        self.assertEqual(detail["certification_number"], "CCOF-12345")
        self.assertIs(detail["cert_is_current"], True)


class FacilityReachesTheAuditExportTests(TestCase):
    """The whole point of the route: the G6.1 block must render for an app-created link."""

    def setUp(self):
        self.company = Company.objects.create(name="Export Co")
        self.establishment = Establishment.objects.create(name="Export Farm", company=self.company)
        self.parcel = Parcel.objects.create(name="Block B", establishment=self.establishment, area=8.0)
        self.product = Product.objects.create(name="Almond")
        self.production = History.objects.create(
            name="Almond 2026",
            parcel=self.parcel,
            product=self.product,
            start_date=timezone.now(),
        )

    def test_no_facility_prints_the_ask(self):
        elements = AuditExportService(self.production, "organic")._build_post_harvest_section()
        self.assertIn("certified organic handler", _text(elements))
        self.assertNotIn("Handler / Facility", _text(elements))

    def test_linked_facility_prints_the_certificate_block(self):
        self.production.post_harvest_facility = PostHarvestFacility.objects.create(
            establishment=self.establishment,
            name="Central Valley Hulling",
            facility_type="huller",
            certification_number="CCOF-12345",
            certifier_name="CCOF Certification Services",
            effective_date=timezone.now().date() - timedelta(days=30),
        )
        self.production.save(update_fields=["post_harvest_facility"])

        text = _text(AuditExportService(self.production, "organic")._build_post_harvest_section())
        self.assertIn("Central Valley Hulling", text)
        self.assertIn("CCOF-12345", text)
        self.assertIn("DOCUMENTED", text)

    def test_stale_certificate_is_flagged_not_passed(self):
        self.production.post_harvest_facility = PostHarvestFacility.objects.create(
            establishment=self.establishment,
            name="Stale Huller",
            facility_type="huller",
            # Older than the ~15-month CCOF G6.1 freshness window.
            effective_date=timezone.now().date() - timedelta(days=600),
        )
        self.production.save(update_fields=["post_harvest_facility"])

        text = _text(AuditExportService(self.production, "organic")._build_post_harvest_section())
        self.assertIn("[GAP]", text)
        self.assertNotIn("DOCUMENTED", text)
