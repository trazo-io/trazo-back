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
from history.models import Production
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
        self.production = Production.objects.create(
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
        return f"/api/productions/{self.production.id}/"

    def test_production_can_be_linked_to_its_own_farms_handler(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(self._url(), {"post_harvest_facilities": [self.facility.id]}, format="json")
        self.assertIn(resp.status_code, (200, 202), resp.content)
        self.production.refresh_from_db()
        self.assertEqual(list(self.production.post_harvest_facilities.values_list("id", flat=True)), [self.facility.id])

    def test_production_cannot_be_linked_to_another_farms_handler(self):
        """Otherwise a stranger's organic certificate prints inside this operation's packet."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(self._url(), {"post_harvest_facilities": [self.foreign_facility.id]}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.production.refresh_from_db()
        self.assertEqual(self.production.post_harvest_facilities.count(), 0)

    def test_a_foreign_handler_is_refused_even_when_a_valid_one_leads_the_list(self):
        """The validator runs over EVERY id — a per-object check would stop at the first.

        Added 2026-08-21 with the single-FK → many-relation change: a list gives the caller a
        place to hide a stranger's facility behind a legitimate one, and that facility's
        organic certificate would then print inside this operation's packet.
        """
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(
            self._url(),
            {"post_harvest_facilities": [self.facility.id, self.foreign_facility.id]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self.production.post_harvest_facilities.count(), 0)

    def test_detail_payload_carries_the_certificate_summary(self):
        self.production.post_harvest_facilities.add(self.facility)
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        details = resp.data.get("post_harvest_facilities_detail")
        self.assertTrue(details, "handler summary missing from the production payload")
        self.assertEqual(details[0]["name"], "Central Valley Hulling")
        self.assertEqual(details[0]["certification_number"], "CCOF-12345")
        self.assertIs(details[0]["cert_is_current"], True)


class FacilityReachesTheAuditExportTests(TestCase):
    """The whole point of the route: the G6.1 block must render for an app-created link."""

    def setUp(self):
        self.company = Company.objects.create(name="Export Co")
        self.establishment = Establishment.objects.create(name="Export Farm", company=self.company)
        self.parcel = Parcel.objects.create(name="Block B", establishment=self.establishment, area=8.0)
        self.product = Product.objects.create(name="Almond")
        self.production = Production.objects.create(
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
        self.production.post_harvest_facilities.add(
            PostHarvestFacility.objects.create(
                establishment=self.establishment,
                name="Central Valley Hulling",
                facility_type="huller",
                certification_number="CCOF-12345",
                certifier_name="CCOF Certification Services",
                effective_date=timezone.now().date() - timedelta(days=30),
            )
        )

        text = _text(AuditExportService(self.production, "organic")._build_post_harvest_section())
        self.assertIn("Central Valley Hulling", text)
        self.assertIn("CCOF-12345", text)
        # Run 7 (R7-01): in-window dates are stated as dates, never as "DOCUMENTED".
        self.assertIn("fall within the ~15-month window", text)
        self.assertNotIn("DOCUMENTED", text)

    def test_both_handlers_of_a_split_grade_lot_print_their_own_certificate(self):
        """🔴 2026-08-21 — one lot, TWO certified handlers.

        Calapooia Bend ships each blueberry season's fresh grade to Organically Grown Company
        and its process grade to Willamette Valley Fruit — two certified operations, separate
        loads, separate bills of lading. Five of that farm's nine shipped lots were that shape,
        and the link was a single ForeignKey, so the operator could record at most half of what
        § 205.272 asks for. Worse than the omission: the packet's "no handler certificate on
        file" REVIEW cleared as soon as ONE was linked, so the second handler's certificate
        silently stopped being asked for.

        Each handler needs its OWN block — its own certificate number, certifier and 15-month
        freshness verdict. One merged block would attach one certificate to both.
        """
        fresh = PostHarvestFacility.objects.create(
            establishment=self.establishment,
            name="Organically Grown Company",
            facility_type="cold_storage",
            certification_number="OTCO-0042",
            certifier_name="Oregon Tilth Certified Organic",
            effective_date=timezone.now().date() - timedelta(days=30),
        )
        process = PostHarvestFacility.objects.create(
            establishment=self.establishment,
            name="Willamette Valley Fruit Co.",
            facility_type="custom",
            certification_number="OTCO-0318",
            certifier_name="Oregon Tilth Certified Organic",
            effective_date=timezone.now().date() - timedelta(days=600),  # stale copy on file
        )
        self.production.post_harvest_facilities.set([fresh, process])

        text = _text(AuditExportService(self.production, "organic")._build_post_harvest_section())
        self.assertIn("Organically Grown Company", text)
        self.assertIn("OTCO-0042", text)
        self.assertIn("Willamette Valley Fruit Co.", text)
        self.assertIn("OTCO-0318", text)
        # Per-handler verdicts, not one verdict covering both: the fresh handler's copy is
        # current, the process handler's is 20 months old.
        self.assertIn("fall within the ~15-month window", text)
        self.assertIn("more than 15 months old", text)

    def test_stale_certificate_is_flagged_not_passed(self):
        self.production.post_harvest_facilities.add(
            PostHarvestFacility.objects.create(
                establishment=self.establishment,
                name="Stale Huller",
                facility_type="huller",
                # Older than the ~15-month CCOF G6.1 freshness window.
                effective_date=timezone.now().date() - timedelta(days=600),
            )
        )

        text = _text(AuditExportService(self.production, "organic")._build_post_harvest_section())
        # A NOP certificate does not expire (§ 205.404(d)) — the COPY ON FILE goes stale,
        # because the certifier reissues after each § 205.406 annual update. The flag used to
        # say "expired", contradicting this same document's Active Certification Summary
        # footnote, and was the only [GAP] in a packet that otherwise flags REVIEW / WARNING /
        # NON-CONFORMANCE.
        self.assertIn("[REVIEW]", text)
        self.assertIn("more than 15 months old", text)
        self.assertNotIn("expired", text)
        self.assertNotIn("[GAP]", text)
        self.assertNotIn("DOCUMENTED", text)
