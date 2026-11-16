"""The operation's own handling and storage facilities, as facility records.

OTCO C7 7.1: "ON FARM FACILITY INFORMATION ... Facility Name; Site Address, City, State/Province, Zip/Postal
Code, Country." 7.2-1: "Attach a facility layout ... that shows the areas used for organic processing and
storage." 7.7-2: each storage facility with its documentation class, "OC, IS, OWN". CCOF G6.4 A1: "Site Name &
Location (full address)." CCOF G6.2 B1: "Storage Location Name & Address / Crops Stored / Type".

An own facility is covered by the operation's own certificate. Before 2026-11-07 the facility register held
only facilities the crop is sent TO, so every certificate check would have called the farm's own cooler an
uncertified handler. These tests pin that it is never looked up, never asked for a certificate, and prints as
OWN on every surface.
"""

import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.services.osp_module_compiler import compile_module_contributions
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import Production
from history.services.audit_export_service import AuditExportService
from history.services.operation_readiness_service import OperationReadinessService
from product.models import Parcel, Product
from users.models import User, WorksIn

AT = "2026-11-07T12:00:00Z"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _flow_text(elements) -> str:
    return " ".join(getattr(el, "text", "") or "" for el in elements)


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Shed Farm LLC")
        self.est = Establishment.objects.create(name="Shed Farm", company=self.company, state="OR")
        self.own = PostHarvestFacility.objects.create(
            establishment=self.est,
            name="Home packing shed",
            facility_type="packer",
            role="both",
            operated_by="this_operation",
            address="100 Farm Rd",
            city="Tangent",
            state="OR",
            postal_code="97389",
            country="USA",
        )
        self.handler = PostHarvestFacility.objects.create(
            establishment=self.est,
            name="Valley Huller",
            facility_type="huller",
            role="handling",
            certification_number="OTCO-1",
            certifier_name="Oregon Tilth",
            effective_date=timezone.now().date(),
        )

    def plan(self, modules):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    key: {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}
                    for key, answers in modules.items()
                },
            },
        )


class ModelAndVerification(_Farm):
    def test_an_own_facility_needs_no_certificate_and_is_never_looked_up(self):
        self.assertTrue(self.own.is_own)
        self.assertFalse(self.own.needs_own_certificate)
        with mock.patch("certifications.services.usda_organic_verifier.USDAOrganicVerifier.verify") as lookup:
            self.assertIsNone(self.own.verify())
        lookup.assert_not_called()
        self.assertEqual(self.own.verification_status, "pending")

    def test_a_third_party_facility_still_needs_one(self):
        self.assertTrue(self.handler.needs_own_certificate)


class Api(_Farm):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(email="shed@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/post-harvest-facilities/"

    def test_an_own_facility_is_created_with_its_full_address_and_no_lookup(self):
        with mock.patch("certifications.views.PostHarvestFacilityViewSet._trigger_background_verification") as trigger:
            resp = self.client.post(
                self.url,
                {
                    "name": "North cooler",
                    "facility_type": "cold_storage",
                    "role": "storage",
                    "operated_by": "this_operation",
                    "address": "1 Cooler Ln",
                    "city": "Tangent",
                    "state": "OR",
                    "postal_code": "97389",
                    "country": "USA",
                },
                format="json",
            )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.data["is_own"])
        self.assertEqual(resp.data["postal_code"], "97389")
        trigger.assert_not_called()

    def test_a_certificate_on_an_own_facility_is_refused(self):
        resp = self.client.post(
            self.url,
            {"name": "Shed", "operated_by": "this_operation", "certification_number": "X-1"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("certification_number", resp.data)

    def test_switching_a_certified_handler_to_own_with_its_certificate_on_is_refused(self):
        resp = self.client.patch(f"{self.url}{self.handler.pk}/", {"operated_by": "this_operation"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("certification_number", resp.data)

    def test_verify_is_refused_for_an_own_facility(self):
        resp = self.client.post(f"{self.url}{self.own.pk}/verify/")
        self.assertEqual(resp.status_code, 400)

    def test_a_layout_uploads_onto_an_own_facility(self):
        resp = self.client.patch(
            f"{self.url}{self.own.pk}/",
            {"layout_document": SimpleUploadedFile("layout.pdf", b"%PDF-1.4 layout", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.own.refresh_from_db()
        self.assertTrue(self.own.layout_document)


class PlanSurfaces(_Farm):
    def test_the_narrative_names_own_facilities_apart_and_never_as_uncertified(self):
        osp = self.plan({"g6_4_handling": {"handling_activities": ["packing"]}})
        text = "\n".join(p for parts in compile_module_contributions(osp).values() for p in parts)
        self.assertIn("[On-farm handling and storage facilities]", text)
        self.assertIn(
            "Home packing shed — Packer / Packing Shed, Stores and handles the crop, 100 Farm Rd, Tangent, OR 97389, "
            "USA; operated by this operation, under its own certificate (OWN); no layout attached.",
            text,
        )
        off_farm = text.split("[Off-farm handlers and storage facilities]", 1)[1]
        self.assertNotIn("Home packing shed", off_farm)
        self.assertIn("Valley Huller", off_farm)

    def test_g6_4_lists_own_facilities_on_page_b(self):
        osp = self.plan({"g6_4_handling": {"handling_activities": ["packing"]}})
        page = _text(generate_module_pdf(osp, "g6_4_handling"))
        self.assertIn("Facilities operated by this operation", page)
        self.assertIn("Home packing shed", page)
        self.assertIn("97389", page)
        self.assertIn("(OWN)", page)
        self.assertNotIn("Valley Huller", page)

    def test_g6_2_lists_them_for_on_farm_storage_only(self):
        page = _text(
            generate_module_pdf(self.plan({"g6_2_storage": {"storage_locations": ["on_farm_cold"]}}), "g6_2_storage")
        )
        self.assertIn("Facilities operated by this operation", page)
        page = _text(
            generate_module_pdf(
                self.plan({"g6_2_storage": {"storage_locations": ["certified_handler"]}}), "g6_2_storage"
            )
        )
        self.assertNotIn("Facilities operated by this operation", page)

    def test_the_off_farm_table_never_calls_the_own_facility_uncertified(self):
        osp = self.plan({"g6_1_harvest_transport": {"handled_by_another_operation": "yes_certified"}})
        page = _text(generate_module_pdf(osp, "g6_1_harvest_transport"))
        self.assertIn("Valley Huller", page)
        self.assertNotIn("Home packing shed", page)

    def test_the_layout_rides_in_the_packet_beside_its_facility(self):
        from certifications.services.packet_attachments import _candidates

        self.own.layout_document = SimpleUploadedFile("layout.pdf", b"%PDF-1.4 layout")
        self.own.save()
        osp = self.plan({"g6_4_handling": {"handling_activities": ["packing"]}})
        paths = [a.zip_path for a, _open in _candidates(osp)]
        self.assertTrue(any(p.startswith(f"facilities/{self.own.pk}-") and "layout" in p for p in paths), paths)
        # Not shipped when no page prints the own-facility table.
        osp = self.plan({"g6_4_handling": {"handling_activities": ["no_onfarm_handling"]}})
        self.assertFalse(any(a.zip_path.startswith("facilities/") for a, _o in _candidates(osp)))


class Readiness(_Farm):
    def test_own_facilities_alone_are_not_a_certificate_to_chase(self):
        self.handler.delete()
        result = OperationReadinessService(self.est)._check_handler_certificates()
        self.assertEqual(result["code"], "handler_certificates.not_applicable")

    def test_an_undated_third_party_certificate_still_flags(self):
        self.handler.effective_date = None
        self.handler.save()
        result = OperationReadinessService(self.est)._check_handler_certificates()
        self.assertEqual(result["code"], "handler_certificates.attention")
        self.assertEqual(result["params"]["undated"], ["Valley Huller"])


class AuditExport(_Farm):
    def setUp(self):
        super().setUp()
        parcel = Parcel.objects.create(name="Block A", establishment=self.est, area=5.0)
        self.production = Production.objects.create(
            name="Pears 2026", parcel=parcel, product=Product.objects.create(name="Pear"), start_date=timezone.now()
        )

    def test_a_linked_own_facility_prints_as_on_farm_and_is_not_counted_as_certified(self):
        self.production.post_harvest_facilities.add(self.own, self.handler)
        text = _flow_text(AuditExportService(self.production, "organic")._build_post_harvest_section())
        self.assertIn("On-Farm Facility (operated by this operation)", text)
        self.assertNotIn("handled by 2 certified operations", text)
